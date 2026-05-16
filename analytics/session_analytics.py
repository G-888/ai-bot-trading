"""
analytics/session_analytics.py — Trading session performance breakdown engine.

Classifies every backtest trade by XAUUSD trading session (UTC):
  Asia/Tokyo   : 00:00 – 08:59
  London       : 08:00 – 12:59
  London/NY    : 13:00 – 16:59  (overlap — highest liquidity)
  New York     : 17:00 – 20:59
  After Hours  : 21:00 – 23:59

Uses backtest_trades.session column if populated, otherwise
falls back to timestamp-based classification.

Python computes all metrics. No mocked data.
"""
import io
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

import storage.database as db

logger = logging.getLogger(__name__)

DARK_BG  = "#0d1117"
GRID_CLR = "#1e2530"
TEXT_CLR = "#e2e8f0"
BULL_CLR = "#00c896"
BEAR_CLR = "#ff4560"
WARN_CLR = "#f6ad55"
FLAT_CLR = "#4a5568"
COLORS   = ["#63b3ed", "#00c896", "#f6ad55", "#fc8181", "#b794f4"]

SESSION_ORDER  = ["Asia", "London", "London/NY", "New York", "After Hours", "Unknown"]
SESSION_ICONS  = {
    "Asia":        "🌏",
    "London":      "🏦",
    "London/NY":   "⚡",
    "New York":    "🗽",
    "After Hours": "🌙",
    "Unknown":     "❓",
}
SESSION_COLORS = {
    "Asia":        "#b794f4",
    "London":      "#63b3ed",
    "London/NY":   "#00c896",
    "New York":    "#f6ad55",
    "After Hours": "#4a5568",
    "Unknown":     "#2d3748",
}


def _classify_by_hour(hour: int) -> str:
    if 0 <= hour <= 7:
        return "Asia"
    if 8 <= hour <= 12:
        return "London"
    if 13 <= hour <= 16:
        return "London/NY"
    if 17 <= hour <= 20:
        return "New York"
    return "After Hours"


def _session_from_trade(trade: dict) -> str:
    """Return session name — prefer stored session column, fall back to timestamp."""
    stored = trade.get("session")
    if stored:
        if "Asia" in stored or "Tokyo" in stored or "Sydney" in stored:
            return "Asia"
        if "Overlap" in stored or "overlap" in stored or "NY" in stored:
            return "London/NY"
        if "London" in stored:
            return "London"
        if "New York" in stored or "NewYork" in stored or "York" in stored:
            return "New York"
        if "After" in stored or "after" in stored or "Pre" in stored:
            return "After Hours"

    ts_raw = trade.get("timestamp")
    if ts_raw:
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return _classify_by_hour(ts.hour)
        except Exception:
            pass

    return "Unknown"


def _compute_session_stats(trades: list[dict]) -> dict[str, dict]:
    """Compute win rate, PnL, expectancy, avg RR per session."""
    by_session: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        sess = _session_from_trade(t)
        by_session[sess].append(t)

    result: dict[str, dict] = {}
    for sess, grp in by_session.items():
        n = len(grp)
        if n == 0:
            continue
        winners  = [t for t in grp if t.get("pnl", 0) > 0]
        losers   = [t for t in grp if t.get("pnl", 0) <= 0]
        win_rate = len(winners) / n * 100
        gross_p  = sum(t.get("pnl", 0) for t in winners)
        gross_l  = abs(sum(t.get("pnl", 0) for t in losers))
        pf       = gross_p / gross_l if gross_l > 0 else (999.0 if gross_p > 0 else 0.0)
        avg_win  = gross_p / len(winners) if winners else 0
        avg_loss = gross_l / len(losers)  if losers  else 0
        exp      = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)
        avg_rr   = sum(t.get("rr_actual", 0) for t in grp) / n
        total_pnl = sum(t.get("pnl", 0) for t in grp)

        result[sess] = {
            "trades":       n,
            "win_rate":     round(win_rate, 1),
            "profit_factor": round(min(pf, 999), 2),
            "expectancy":   round(exp, 3),
            "avg_rr":       round(avg_rr, 2),
            "total_pnl":    round(total_pnl, 2),
            "gross_profit": round(gross_p, 2),
            "gross_loss":   round(gross_l, 2),
        }
    return result


def _hour_heatmap(trades: list[dict]) -> dict[int, dict]:
    """Build hour-of-day win rate map (0-23 UTC)."""
    by_hour: dict[int, list[float]] = defaultdict(list)
    for t in trades:
        ts_raw = t.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            by_hour[ts.hour].append(t.get("pnl", 0))
        except Exception:
            pass
    result = {}
    for h, pnls in by_hour.items():
        wins = sum(1 for p in pnls if p > 0)
        result[h] = {
            "trades":   len(pnls),
            "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def run_session_analysis(stats: dict | None = None) -> dict[str, dict]:
    """
    Run session analysis for all strategies.
    Returns: dict[strategy_key] → {label, sessions, best, worst, hour_map}
    """
    from analytics.performance import get_performance_stats, _get_all_trades

    if stats is None:
        stats = get_performance_stats()

    all_trades = _get_all_trades()
    trades_by_run: dict[int, dict] = {}
    runs = db.get_backtest_runs(limit=500)
    for r in runs:
        trades_by_run[r["id"]] = r

    trades_by_strat: dict[str, list[dict]] = defaultdict(list)
    for t in all_trades:
        rid = t.get("run_id")
        run = trades_by_run.get(rid)
        if run:
            trades_by_strat[run["strategy"]].append(t)

    results: dict[str, dict] = {}
    for strat_key, s in stats.items():
        trades = trades_by_strat.get(strat_key, s.get("all_trades", []))
        session_stats = _compute_session_stats(trades)
        hour_map      = _hour_heatmap(trades)

        viable = {k: v for k, v in session_stats.items() if v["trades"] >= 3}
        best  = max(viable, key=lambda k: viable[k]["win_rate"]) if viable else None
        worst = min(viable, key=lambda k: viable[k]["win_rate"]) if viable else None

        avoid_sessions   = [k for k, v in viable.items() if v["win_rate"] < 45]
        strong_sessions  = [k for k, v in viable.items() if v["win_rate"] > 60]

        results[strat_key] = {
            "label":          s["label"],
            "sessions":       session_stats,
            "best_session":   best,
            "worst_session":  worst,
            "avoid":          avoid_sessions,
            "strong":         strong_sessions,
            "hour_map":       hour_map,
            "total_trades":   len(trades),
        }

    return results


def format_session_report(analysis: dict[str, dict], strategy: str | None = None) -> str:
    if not analysis:
        return (
            "No session data available.\n\n"
            "Run backtests first:\n"
            "/backtest fib 1H 30d\n"
            "/backtest smc 1H 30d"
        )

    targets = {strategy: analysis[strategy]} if strategy and strategy in analysis else analysis
    lines   = []

    for strat_key, d in targets.items():
        label    = d["label"]
        sessions = d["sessions"]
        best     = d["best_session"]
        worst    = d["worst_session"]
        total    = d["total_trades"]

        lines.append(f"┌{'─' * 34}┐")
        lines.append(f"│ SESSION ANALYTICS — {label.upper():<13}│")
        lines.append(f"│ {total} trades analysed{' ' * (16 - len(str(total)))}│")
        lines.append(f"├{'─' * 34}┤")

        for sess in SESSION_ORDER:
            sd = sessions.get(sess)
            if not sd or sd["trades"] < 1:
                continue
            wr  = sd["win_rate"]
            bar = "█" * int(wr // 10) + "░" * (10 - int(wr // 10))
            icon = SESSION_ICONS.get(sess, "·")
            flag = ""
            if sess == best  and wr > 50:
                flag = " ✓BEST"
            if sess == worst and wr < 50:
                flag = " ✗WEAK"
            lines.append(f"│ {icon} {sess:<11} {wr:>5.1f}% WR {bar}{flag}")

        lines.append(f"├{'─' * 34}┤")

        for sess in SESSION_ORDER:
            sd = sessions.get(sess)
            if not sd or sd["trades"] < 3:
                continue
            pf_s = f"{sd['profit_factor']:.2f}" if sd["profit_factor"] < 100 else "∞"
            lines.append(
                f"│ {sess:<13} n={sd['trades']:<3} "
                f"PF={pf_s:<6} E={sd['expectancy']:+.3f}"
            )

        lines.append(f"├{'─' * 34}┤")

        if d["strong"]:
            lines.append(f"│ TRADE  : {', '.join(d['strong'])}")
        if d["avoid"]:
            lines.append(f"│ AVOID  : {', '.join(d['avoid'])}")
        if best:
            lines.append(f"│ BEST   : {best} ({sessions[best]['win_rate']:.0f}% WR)")
        if worst:
            lines.append(f"│ WORST  : {worst} ({sessions[worst]['win_rate']:.0f}% WR)")

        lines.append(f"└{'─' * 34}┘")
        lines.append("")

    if len(targets) > 1:
        lines.append("Cross-Strategy Best Sessions:")
        for strat_key, d in targets.items():
            b = d.get("best_session", "—")
            w = d.get("worst_session", "—")
            wr_b = d["sessions"].get(b, {}).get("win_rate", 0) if b else 0
            lines.append(f"  {d['label']:<14} Best: {b} ({wr_b:.0f}%)")
        lines.append("")

    return "\n".join(lines)


def generate_session_chart(analysis: dict[str, dict]) -> io.BytesIO:
    """Multi-panel session performance chart."""
    strat_keys = list(analysis.keys())
    n_strats   = len(strat_keys)

    if not strat_keys:
        return _empty_chart("No session data")

    fig = plt.figure(figsize=(7.5, 8.0), facecolor=DARK_BG)
    gs  = gridspec.GridSpec(2 + (1 if n_strats > 1 else 0), 1, hspace=0.45)

    ax_main = fig.add_subplot(gs[0])
    ax_pf   = fig.add_subplot(gs[1])

    _style_ax(ax_main); _style_ax(ax_pf)

    all_sessions = [s for s in SESSION_ORDER if s != "Unknown"]

    for i, sk in enumerate(strat_keys[:4]):
        d     = analysis[sk]
        wrs   = [d["sessions"].get(s, {}).get("win_rate", 0) for s in all_sessions]
        clr   = COLORS[i % len(COLORS)]
        x_pos = [j + i * 0.2 - (n_strats - 1) * 0.1 for j in range(len(all_sessions))]
        bars  = ax_main.bar(x_pos, wrs, width=0.18, color=clr, label=d["label"],
                            zorder=3, alpha=0.85)

    ax_main.axhline(50, color=WARN_CLR, linewidth=0.8, linestyle="--", alpha=0.7)
    ax_main.set_xticks(range(len(all_sessions)))
    ax_main.set_xticklabels(
        [f"{SESSION_ICONS.get(s, '')} {s}" for s in all_sessions],
        fontsize=6.5, rotation=15,
    )
    ax_main.set_ylabel("Win Rate %", color=TEXT_CLR, fontsize=7)
    ax_main.set_ylim(0, 100)
    ax_main.set_title("Win Rate by Trading Session", color=TEXT_CLR, fontsize=9, fontweight="bold")
    ax_main.legend(fontsize=6.5, facecolor=DARK_BG, labelcolor=TEXT_CLR,
                   loc="upper right", framealpha=0.6)

    for i, sk in enumerate(strat_keys[:4]):
        d    = analysis[sk]
        pnls = [d["sessions"].get(s, {}).get("total_pnl", 0) for s in all_sessions]
        clr  = COLORS[i % len(COLORS)]
        x_pos = [j + i * 0.2 - (n_strats - 1) * 0.1 for j in range(len(all_sessions))]
        ax_pf.bar(x_pos, pnls, width=0.18, color=[
            BULL_CLR if p >= 0 else BEAR_CLR for p in pnls
        ], zorder=3, alpha=0.85)

    ax_pf.axhline(0, color=FLAT_CLR, linewidth=0.8, linestyle="--")
    ax_pf.set_xticks(range(len(all_sessions)))
    ax_pf.set_xticklabels(
        [f"{SESSION_ICONS.get(s, '')} {s}" for s in all_sessions],
        fontsize=6.5, rotation=15,
    )
    ax_pf.set_ylabel("Total PnL (pts)", color=TEXT_CLR, fontsize=7)
    ax_pf.set_title("Net PnL by Trading Session", color=TEXT_CLR, fontsize=9, fontweight="bold")

    if n_strats > 1:
        ax_hr = fig.add_subplot(gs[2])
        _style_ax(ax_hr)
        _draw_hour_heatmap(ax_hr, analysis)

    fig.suptitle("XAUUSD  Session Performance Analytics",
                 color=TEXT_CLR, fontsize=10, fontweight="bold", y=0.99)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


def _draw_hour_heatmap(ax, analysis: dict[str, dict]) -> None:
    """Hour-of-day aggregated win rate heatmap."""
    agg: dict[int, list[float]] = defaultdict(list)
    for d in analysis.values():
        for h, hd in d.get("hour_map", {}).items():
            if hd["trades"] >= 2:
                agg[h].append(hd["win_rate"])

    hours   = sorted(agg.keys())
    avg_wrs = [sum(agg[h]) / len(agg[h]) for h in hours]

    if not hours:
        ax.text(0.5, 0.5, "No timestamp data", ha="center", va="center",
                color=TEXT_CLR, fontsize=8, transform=ax.transAxes)
        ax.set_title("Hour-of-Day Win Rate", color=TEXT_CLR, fontsize=8, fontweight="bold")
        return

    clrs = [BULL_CLR if w >= 50 else BEAR_CLR for w in avg_wrs]
    ax.bar(hours, avg_wrs, color=clrs, width=0.7, zorder=3)
    ax.axhline(50, color=WARN_CLR, linewidth=0.7, linestyle="--", alpha=0.7)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)], fontsize=5.5)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Win Rate %", color=TEXT_CLR, fontsize=6.5)
    ax.set_xlabel("Hour UTC", color=TEXT_CLR, fontsize=6.5)
    ax.set_title("Hour-of-Day Win Rate (all strategies)", color=TEXT_CLR,
                 fontsize=8, fontweight="bold")

    for lo, hi, lbl in [(0, 8, "Asia"), (8, 13, "LON"), (13, 17, "Overlap"), (17, 21, "NY")]:
        ax.axvspan(lo - 0.4, hi - 0.6, alpha=0.06,
                   color=list(SESSION_COLORS.values())[
                       list(SESSION_COLORS.keys()).index(
                           "Asia" if lo == 0 else "London" if lo == 8
                           else "London/NY" if lo == 13 else "New York"
                       )
                   ])


def _style_ax(ax) -> None:
    ax.set_facecolor(DARK_BG)
    ax.tick_params(colors=TEXT_CLR, labelsize=6.5)
    for sp in ax.spines.values():
        sp.set_color(GRID_CLR)
    ax.yaxis.label.set_color(TEXT_CLR)
    ax.xaxis.label.set_color(TEXT_CLR)
    ax.grid(axis="y", color=GRID_CLR, linewidth=0.4, alpha=0.5, zorder=0)


def _empty_chart(msg: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6, 2.5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG); ax.axis("off")
    ax.text(0.5, 0.5, msg, ha="center", va="center", color=TEXT_CLR, fontsize=9)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf
