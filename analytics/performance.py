"""
analytics/performance.py — Strategy performance analytics engine.

Pulls real data from SQLite backtest tables.
Python computes all metrics. AI only explains outputs.
"""
import io
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta

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
FLAT_CLR = "#4a5568"
ACCENT   = "#63b3ed"
WARN_CLR = "#f6ad55"
COLORS   = ["#63b3ed", "#00c896", "#f6ad55", "#fc8181", "#b794f4", "#76e4f7"]

STRATEGY_LABELS = {
    "fib":        "Fibonacci",
    "fibonacci":  "Fibonacci",
    "smc":        "SMC",
    "confluence": "Confluence",
    "momentum":   "Momentum",
    "session":    "Session",
    "voting":     "Voting",
}


# ── DB helpers ───────────────────────────────────────────────────────────────────

def _get_all_runs() -> list[dict]:
    return db.get_backtest_runs(limit=500)


def _get_trades_for_run(run_id: int) -> list[dict]:
    with db._lock, db._conn() as c:
        rows = c.execute(
            "SELECT * FROM backtest_trades WHERE run_id=?", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def _get_all_trades() -> list[dict]:
    with db._lock, db._conn() as c:
        rows = c.execute("SELECT * FROM backtest_trades").fetchall()
        return [dict(r) for r in rows]


def _normalize_strategy(name: str) -> str:
    return STRATEGY_LABELS.get(name.lower(), name.title())


# ── Core analytics ───────────────────────────────────────────────────────────────

def _compute_strategy_stats(runs: list[dict], trades: list[dict]) -> dict[str, dict]:
    """Aggregate runs and trades into per-strategy performance stats."""
    by_strat: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_strat[r["strategy"]].append(r)

    trade_by_run: dict[int, list[dict]] = defaultdict(list)
    for t in trades:
        trade_by_run[t["run_id"]].append(t)

    result: dict[str, dict] = {}
    for strat, strat_runs in by_strat.items():
        all_trades = []
        for r in strat_runs:
            all_trades.extend(trade_by_run.get(r["id"], []))

        if not all_trades:
            continue

        winners = [t for t in all_trades if t.get("pnl", 0) > 0]
        losers  = [t for t in all_trades if t.get("pnl", 0) <= 0]
        n = len(all_trades)

        win_rate = len(winners) / n * 100 if n > 0 else 0
        gross_profit = sum(t.get("pnl", 0) for t in winners)
        gross_loss   = abs(sum(t.get("pnl", 0) for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_win  = gross_profit / len(winners) if winners else 0
        avg_loss = gross_loss   / len(losers)  if losers  else 0
        expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)
        avg_rr = sum(t.get("rr_actual", 0) for t in all_trades) / n if n > 0 else 0
        avg_conf = sum(t.get("confidence", 0) for t in all_trades) / n if n > 0 else 0
        total_pnl = sum(t.get("pnl", 0) for t in all_trades)
        avg_duration = sum(t.get("duration_bars", 0) for t in all_trades) / n if n > 0 else 0

        equity = _build_equity_curve(all_trades)
        max_dd = _max_drawdown(equity)

        sharpe = _sharpe(all_trades)

        regime_stats = _regime_split(all_trades)
        rolling_30 = _rolling_winrate(all_trades, days=30)
        rolling_90 = _rolling_winrate(all_trades, days=90)
        vol_adj_score = _volatility_adjusted_score(win_rate, profit_factor, max_dd, n)

        result[strat] = {
            "label":          _normalize_strategy(strat),
            "total_trades":   n,
            "total_runs":     len(strat_runs),
            "win_rate":       round(win_rate, 2),
            "loss_rate":      round(100 - win_rate, 2),
            "profit_factor":  round(profit_factor, 3) if profit_factor != float("inf") else 999,
            "expectancy":     round(expectancy, 3),
            "avg_rr":         round(avg_rr, 3),
            "max_drawdown":   round(max_dd, 2),
            "total_pnl":      round(total_pnl, 2),
            "sharpe":         round(sharpe, 3),
            "avg_confidence": round(avg_conf, 1),
            "avg_duration":   round(avg_duration, 1),
            "vol_adj_score":  round(vol_adj_score, 2),
            "rolling_30d_wr": round(rolling_30, 2),
            "rolling_90d_wr": round(rolling_90, 2),
            "regime_stats":   regime_stats,
            "equity_curve":   equity,
            "all_trades":     all_trades,
        }

    return result


def _build_equity_curve(trades: list[dict]) -> list[float]:
    curve = [0.0]
    total = 0.0
    for t in trades:
        total += t.get("pnl", 0)
        curve.append(round(total, 2))
    return curve


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe(trades: list[dict]) -> float:
    if len(trades) < 2:
        return 0.0
    pnls = [t.get("pnl", 0) for t in trades]
    n = len(pnls)
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0
    return (mean / std * math.sqrt(n)) if std > 0 else 0.0


def _regime_split(trades: list[dict]) -> dict:
    by_regime: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        regime = t.get("regime") or "Unknown"
        if "Trend" in regime or "TREND" in regime:
            key = "Trending"
        elif "Rang" in regime or "RANG" in regime:
            key = "Ranging"
        elif "Volat" in regime or "VOLAT" in regime:
            key = "Volatile"
        elif "Compress" in regime or "COMPRESS" in regime:
            key = "Compression"
        elif "Expan" in regime or "EXPAN" in regime:
            key = "Expansion"
        else:
            key = "Unknown"
        by_regime[key].append(t.get("pnl", 0))

    result = {}
    for regime, pnls in by_regime.items():
        wins = sum(1 for p in pnls if p > 0)
        result[regime] = {
            "trades":   len(pnls),
            "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def _rolling_winrate(trades: list[dict], days: int) -> float:
    """Rolling win rate for most recent N days worth of trades."""
    if not trades:
        return 0.0
    cutoff_ts = None
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        recent = []
        for t in trades:
            ts_raw = t.get("timestamp", "")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    recent.append(t)
            except Exception:
                recent.append(t)
        if not recent:
            recent = trades[-min(30, len(trades)):]
        wins = sum(1 for t in recent if t.get("pnl", 0) > 0)
        return wins / len(recent) * 100 if recent else 0.0
    except Exception:
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        return wins / len(trades) * 100 if trades else 0.0


def _volatility_adjusted_score(win_rate: float, pf: float, max_dd: float, n: int) -> float:
    """
    Composite score 0-100 blending win rate, profit factor, and drawdown control.
    Penalised for small sample size.
    """
    if n == 0:
        return 0.0
    pf_capped = min(pf, 5.0)
    pf_score  = (pf_capped / 5.0) * 30
    wr_score  = (win_rate / 100) * 35
    dd_score  = max(0, 1.0 - max_dd / 200) * 25
    sample_bonus = min(n / 50, 1.0) * 10
    return round(pf_score + wr_score + dd_score + sample_bonus, 2)


# ── Report text formatter ────────────────────────────────────────────────────────

def format_performance_report(stats: dict[str, dict]) -> str:
    if not stats:
        return (
            "No backtest data found.\n\n"
            "Run backtests first:\n"
            "/backtest fib 1H 30d\n"
            "/backtest smc 1H 30d\n"
            "/backtest confluence 1H 30d"
        )

    lines = ["Institutional Performance Report", "=" * 34, ""]
    for strat, s in sorted(stats.items(), key=lambda x: -x[1]["vol_adj_score"]):
        pf_str = f"{s['profit_factor']:.2f}" if s['profit_factor'] < 100 else "∞"
        wr_bar = "█" * int(s["win_rate"] // 10) + "░" * (10 - int(s["win_rate"] // 10))
        score_bar = "█" * int(s["vol_adj_score"] // 10) + "░" * (10 - int(s["vol_adj_score"] // 10))

        lines.append(f"[ {s['label']} ]")
        lines.append(f"  Trades:     {s['total_trades']}  (runs: {s['total_runs']})")
        lines.append(f"  Win Rate:   [{wr_bar}] {s['win_rate']:.1f}%")
        lines.append(f"  Expectancy: {s['expectancy']:+.3f} pts")
        lines.append(f"  Avg RR:     {s['avg_rr']:.2f}")
        lines.append(f"  PF:         {pf_str}")
        lines.append(f"  Max DD:     {s['max_drawdown']:.2f} pts")
        lines.append(f"  Sharpe:     {s['sharpe']:.2f}")
        lines.append(f"  30d WR:     {s['rolling_30d_wr']:.1f}%")
        lines.append(f"  90d WR:     {s['rolling_90d_wr']:.1f}%")
        lines.append(f"  Vol Score:  [{score_bar}] {s['vol_adj_score']:.1f}/100")

        regime = s.get("regime_stats", {})
        if regime:
            lines.append("  Regime Breakdown:")
            for rname, rd in regime.items():
                if rd["trades"] > 0:
                    lines.append(f"    {rname:<12} {rd['win_rate']:.0f}% WR  {rd['total_pnl']:+.1f}pts")
        lines.append("")

    return "\n".join(lines)


# ── Chart generation ─────────────────────────────────────────────────────────────

def generate_performance_charts(stats: dict[str, dict]) -> io.BytesIO:
    """Generate multi-panel performance comparison chart."""
    if not stats:
        fig, ax = plt.subplots(figsize=(6, 3), facecolor=DARK_BG)
        ax.set_facecolor(DARK_BG)
        ax.text(0.5, 0.5, "No data — run /backtest first",
                ha="center", va="center", color=TEXT_CLR, fontsize=10)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=DARK_BG)
        buf.seek(0)
        plt.close(fig)
        return buf

    strat_keys = list(stats.keys())
    n = len(strat_keys)

    fig = plt.figure(figsize=(7.5, 8.0), facecolor=DARK_BG)
    gs  = gridspec.GridSpec(3, 2, hspace=0.45, wspace=0.35)

    ax_eq   = fig.add_subplot(gs[0, :])
    ax_wr   = fig.add_subplot(gs[1, 0])
    ax_pf   = fig.add_subplot(gs[1, 1])
    ax_bar  = fig.add_subplot(gs[2, :])

    _style_ax(ax_eq); _style_ax(ax_wr); _style_ax(ax_pf); _style_ax(ax_bar)

    for i, sk in enumerate(strat_keys):
        s   = stats[sk]
        eq  = s["equity_curve"]
        clr = COLORS[i % len(COLORS)]
        ax_eq.plot(range(len(eq)), eq, color=clr, linewidth=1.4,
                   label=s["label"], zorder=3)

    ax_eq.axhline(0, color=FLAT_CLR, linewidth=0.7, linestyle="--")
    ax_eq.set_title("Equity Curves", color=TEXT_CLR, fontsize=8.5, fontweight="bold")
    ax_eq.legend(fontsize=6.5, facecolor=DARK_BG, labelcolor=TEXT_CLR,
                 loc="upper left", framealpha=0.6)
    ax_eq.set_ylabel("PnL (pts)", color=TEXT_CLR, fontsize=7)

    labels = [stats[sk]["label"] for sk in strat_keys]
    win_rates = [stats[sk]["win_rate"] for sk in strat_keys]
    clrs = [BULL_CLR if w >= 50 else BEAR_CLR for w in win_rates]
    bars = ax_wr.bar(range(n), win_rates, color=clrs, width=0.6, zorder=3)
    ax_wr.axhline(50, color=WARN_CLR, linewidth=0.8, linestyle="--", alpha=0.7)
    ax_wr.set_xticks(range(n))
    ax_wr.set_xticklabels(labels, fontsize=6.5, rotation=15)
    ax_wr.set_title("Win Rate %", color=TEXT_CLR, fontsize=8, fontweight="bold")
    ax_wr.set_ylim(0, 100)
    for bar, val in zip(bars, win_rates):
        ax_wr.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                   f"{val:.0f}%", ha="center", va="bottom", fontsize=6, color=TEXT_CLR)

    pf_vals = [min(stats[sk]["profit_factor"], 5.0) for sk in strat_keys]
    pf_clrs = [BULL_CLR if v >= 1.5 else (WARN_CLR if v >= 1.0 else BEAR_CLR) for v in pf_vals]
    bars2 = ax_pf.bar(range(n), pf_vals, color=pf_clrs, width=0.6, zorder=3)
    ax_pf.axhline(1.0, color=WARN_CLR, linewidth=0.8, linestyle="--", alpha=0.7)
    ax_pf.set_xticks(range(n))
    ax_pf.set_xticklabels(labels, fontsize=6.5, rotation=15)
    ax_pf.set_title("Profit Factor", color=TEXT_CLR, fontsize=8, fontweight="bold")
    for bar, val in zip(bars2, pf_vals):
        ax_pf.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                   f"{val:.1f}", ha="center", va="bottom", fontsize=6, color=TEXT_CLR)

    scores = [stats[sk]["vol_adj_score"] for sk in strat_keys]
    score_clrs = [COLORS[i % len(COLORS)] for i in range(n)]
    bars3 = ax_bar.barh(range(n), scores, color=score_clrs, height=0.6, zorder=3)
    ax_bar.set_yticks(range(n))
    ax_bar.set_yticklabels(labels, fontsize=7.5)
    ax_bar.set_xlim(0, 100)
    ax_bar.axvline(50, color=FLAT_CLR, linewidth=0.7, linestyle="--", alpha=0.7)
    ax_bar.set_title("Volatility-Adjusted Score", color=TEXT_CLR, fontsize=8, fontweight="bold")
    for bar, val in zip(bars3, scores):
        ax_bar.text(val + 0.5, bar.get_y() + bar.get_height() / 2,
                    f"{val:.1f}", va="center", fontsize=6.5, color=TEXT_CLR)

    fig.suptitle("XAUUSD  Strategy Performance Dashboard",
                 color=TEXT_CLR, fontsize=10, fontweight="bold", y=0.98)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_monthly_heatmap(stats: dict[str, dict]) -> io.BytesIO:
    """Generate monthly performance heatmap for the top strategy by vol score."""
    best_key = max(stats, key=lambda k: stats[k]["vol_adj_score"]) if stats else None
    if not best_key:
        return _empty_chart("No data for monthly heatmap")

    trades = stats[best_key].get("all_trades", [])
    label  = stats[best_key]["label"]

    monthly: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        ts_raw = t.get("timestamp", "")
        pnl    = t.get("pnl", 0)
        try:
            ts    = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            month = ts.strftime("%Y-%m")
        except Exception:
            month = "Unknown"
        monthly[month].append(pnl)

    months = sorted(monthly.keys())
    if not months:
        return _empty_chart("No monthly data available")

    month_pnls = [sum(monthly[m]) for m in months]
    month_labels = [m[-5:] for m in months]

    fig, ax = plt.subplots(figsize=(7, 3), facecolor=DARK_BG)
    _style_ax(ax)

    clrs = [BULL_CLR if p >= 0 else BEAR_CLR for p in month_pnls]
    bars = ax.bar(range(len(months)), month_pnls, color=clrs, width=0.7, zorder=3)
    ax.axhline(0, color=FLAT_CLR, linewidth=0.8, linestyle="--")
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(month_labels, fontsize=7, rotation=30)
    ax.set_title(f"Monthly PnL — {label}", color=TEXT_CLR, fontsize=9, fontweight="bold")
    ax.set_ylabel("PnL (pts)", color=TEXT_CLR, fontsize=7)

    for bar, val in zip(bars, month_pnls):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (0.3 if val >= 0 else -0.5),
                f"{val:+.1f}", ha="center", va="bottom" if val >= 0 else "top",
                fontsize=5.5, color=TEXT_CLR)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


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
    ax.set_facecolor(DARK_BG)
    ax.text(0.5, 0.5, msg, ha="center", va="center", color=TEXT_CLR, fontsize=9)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


# ── Public entry point ───────────────────────────────────────────────────────────

def get_performance_stats() -> dict[str, dict]:
    runs   = _get_all_runs()
    trades = _get_all_trades()
    return _compute_strategy_stats(runs, trades)
