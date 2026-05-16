"""
analytics/decay.py — Strategy edge deterioration detection engine.

Computes rolling metrics (7d / 30d / 90d) from real historical data
stored in performance_snapshots, backtest_runs, and backtest_trades.

Python computes ALL metrics. No mocked data. No lookahead.
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
import numpy as np

import storage.database as db

logger = logging.getLogger(__name__)

DARK_BG  = "#0d1117"
GRID_CLR = "#1e2530"
TEXT_CLR = "#e2e8f0"
BULL_CLR = "#00c896"
BEAR_CLR = "#ff4560"
WARN_CLR = "#f6ad55"
FLAT_CLR = "#4a5568"
ACCENT   = "#63b3ed"
CRIT_CLR = "#fc8181"
COLORS   = ["#63b3ed", "#00c896", "#f6ad55", "#fc8181", "#b794f4", "#76e4f7"]

EDGE_GRADES = [
    (90, "Institutional Grade"),
    (75, "Strong Edge"),
    (60, "Degrading"),
    (40, "Weak"),
    (0,  "Critical Failure"),
]

DECAY_THRESHOLDS = {
    "wr_delta_30_90":    -8.0,   # 30d WR vs 90d WR delta  (pp)
    "wr_delta_7_30":     -10.0,  # 7d WR vs 30d WR delta   (pp)
    "exp_delta_pct":     -25.0,  # expectancy drop %
    "pf_delta_pct":      -20.0,  # profit factor drop %
    "dd_expansion_pct":  +30.0,  # drawdown expansion %
    "overconf_delta":    -10.0,  # high-conf win rate vs baseline (pp)
    "saturation_pct":    +60.0,  # signal volume increase %
}


# ── Rolling data extraction ──────────────────────────────────────────────────────

def _trades_in_window(trades: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = []
    for t in trades:
        ts_raw = t.get("timestamp", "")
        if not ts_raw:
            result.append(t)
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                result.append(t)
        except Exception:
            result.append(t)
    return result


def _rolling_metrics(trades: list[dict], days: int) -> dict:
    """Compute key metrics for trades within `days` window."""
    window = _trades_in_window(trades, days)
    if not window:
        return {"trades": 0, "win_rate": 0, "profit_factor": 0,
                "expectancy": 0, "max_drawdown": 0, "avg_confidence": 0}

    n = len(window)
    winners = [t for t in window if t.get("pnl", 0) > 0]
    losers  = [t for t in window if t.get("pnl", 0) <= 0]
    gross_p = sum(t.get("pnl", 0) for t in winners)
    gross_l = abs(sum(t.get("pnl", 0) for t in losers))
    win_rate = len(winners) / n * 100 if n > 0 else 0
    avg_win  = gross_p / len(winners) if winners else 0
    avg_loss = gross_l / len(losers)  if losers  else 0
    pf       = gross_p / gross_l if gross_l > 0 else (999.0 if gross_p > 0 else 0.0)
    exp      = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)
    avg_conf = sum(t.get("confidence", 0) for t in window) / n if n > 0 else 0

    equity = [0.0]
    total  = 0.0
    for t in window:
        total += t.get("pnl", 0)
        equity.append(total)
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        max_dd = max(max_dd, peak - v)

    return {
        "trades":          n,
        "win_rate":        round(win_rate, 2),
        "profit_factor":   round(min(pf, 999), 3),
        "expectancy":      round(exp, 3),
        "max_drawdown":    round(max_dd, 2),
        "avg_confidence":  round(avg_conf, 1),
    }


def _snapshots_rolling(strategy: str, days: int) -> dict:
    """Pull performance_snapshots and average metrics over `days`."""
    snaps = db.get_performance_snapshots(strategy, limit=days + 10)
    if not snaps:
        return {}
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [s for s in snaps if s.get("snapshot_date", "0") >= cutoff_date]
    if not recent:
        recent = snaps[:min(days, len(snaps))]
    if not recent:
        return {}
    avg = lambda key: sum(s.get(key, 0) for s in recent) / len(recent)
    return {
        "win_rate":      round(avg("win_rate"), 2),
        "profit_factor": round(avg("profit_factor"), 3),
        "expectancy":    round(avg("expectancy"), 3),
        "vol_adj_score": round(avg("vol_adj_score"), 2),
        "samples":       len(recent),
    }


# ── Decay detections ─────────────────────────────────────────────────────────────

def _detect_win_rate_decay(m7: dict, m30: dict, m90: dict) -> list[dict]:
    issues = []
    wr7, wr30, wr90 = m7.get("win_rate", 0), m30.get("win_rate", 0), m90.get("win_rate", 0)

    if wr90 > 0 and m30.get("trades", 0) >= 5 and m90.get("trades", 0) >= 5:
        delta_30_90 = wr30 - wr90
        if delta_30_90 < DECAY_THRESHOLDS["wr_delta_30_90"]:
            severity = "CRITICAL" if delta_30_90 < -20 else "WARNING"
            issues.append({
                "code": "WIN_RATE_DECAY",
                "severity": severity,
                "msg": f"Win rate declining: 90d={wr90:.1f}%  30d={wr30:.1f}%  ({delta_30_90:+.1f}pp)",
                "metric": "win_rate",
                "delta": delta_30_90,
            })

    if wr30 > 0 and m7.get("trades", 0) >= 3 and m30.get("trades", 0) >= 5:
        delta_7_30 = wr7 - wr30
        if delta_7_30 < DECAY_THRESHOLDS["wr_delta_7_30"]:
            severity = "CRITICAL" if delta_7_30 < -20 else "WARNING"
            issues.append({
                "code": "WIN_RATE_COLLAPSE",
                "severity": severity,
                "msg": f"Sharp recent decline: 30d={wr30:.1f}%  7d={wr7:.1f}%  ({delta_7_30:+.1f}pp)",
                "metric": "win_rate",
                "delta": delta_7_30,
            })

    return issues


def _detect_expectancy_decay(m30: dict, m90: dict) -> list[dict]:
    issues = []
    e30, e90 = m30.get("expectancy", 0), m90.get("expectancy", 0)
    if abs(e90) < 0.001 or m30.get("trades", 0) < 5:
        return []
    pct_change = (e30 - e90) / abs(e90) * 100 if e90 != 0 else 0
    if pct_change < DECAY_THRESHOLDS["exp_delta_pct"]:
        severity = "CRITICAL" if pct_change < -50 else "WARNING"
        issues.append({
            "code": "EXPECTANCY_COLLAPSE",
            "severity": severity,
            "msg": f"Expectancy dropped {abs(pct_change):.0f}%: 90d={e90:+.3f}  30d={e30:+.3f}",
            "metric": "expectancy",
            "delta": pct_change,
        })
    return issues


def _detect_pf_deterioration(m30: dict, m90: dict) -> list[dict]:
    issues = []
    pf30, pf90 = m30.get("profit_factor", 0), m90.get("profit_factor", 0)
    if pf90 <= 0 or pf90 >= 999 or m30.get("trades", 0) < 5:
        return []
    pct_change = (pf30 - pf90) / pf90 * 100
    if pct_change < DECAY_THRESHOLDS["pf_delta_pct"]:
        severity = "CRITICAL" if pf30 < 1.0 else "WARNING"
        issues.append({
            "code": "PROFIT_FACTOR_DROP",
            "severity": severity,
            "msg": f"Profit factor falling: 90d={pf90:.2f}  30d={pf30:.2f}  ({pct_change:+.0f}%)",
            "metric": "profit_factor",
            "delta": pct_change,
        })
    return issues


def _detect_drawdown_expansion(m30: dict, m90: dict) -> list[dict]:
    issues = []
    dd30, dd90 = m30.get("max_drawdown", 0), m90.get("max_drawdown", 0)
    if dd90 < 0.01 or m30.get("trades", 0) < 5:
        return []
    pct_change = (dd30 - dd90) / dd90 * 100
    if pct_change > DECAY_THRESHOLDS["dd_expansion_pct"]:
        severity = "CRITICAL" if pct_change > 80 else "WARNING"
        issues.append({
            "code": "DRAWDOWN_EXPANSION",
            "severity": severity,
            "msg": f"Drawdown expanding: 90d={dd90:.2f}  30d={dd30:.2f}  (+{pct_change:.0f}%)",
            "metric": "max_drawdown",
            "delta": pct_change,
        })
    return issues


def _detect_regime_failure(trades_all: list[dict]) -> list[dict]:
    issues = []
    by_regime: dict[str, list[float]] = defaultdict(list)
    for t in trades_all:
        r = t.get("regime") or "Unknown"
        if "Trend" in r or "TREND" in r:
            key = "Trending"
        elif "Rang" in r or "RANG" in r:
            key = "Ranging"
        elif "Volat" in r or "VOLAT" in r:
            key = "Volatile"
        elif "Compress" in r or "COMPRESS" in r:
            key = "Compression"
        elif "Expan" in r or "EXPAN" in r:
            key = "Expansion"
        else:
            key = "Unknown"
        by_regime[key].append(t.get("pnl", 0))

    if len(by_regime) < 2:
        return issues

    regime_wr: dict[str, float] = {}
    for regime, pnls in by_regime.items():
        if len(pnls) < 5:
            continue
        wins = sum(1 for p in pnls if p > 0)
        regime_wr[regime] = wins / len(pnls) * 100

    if not regime_wr:
        return issues

    best  = max(regime_wr, key=regime_wr.get)
    worst = min(regime_wr, key=regime_wr.get)
    spread = regime_wr[best] - regime_wr[worst]

    if spread > 25:
        severity = "CRITICAL" if regime_wr[worst] < 35 else "WARNING"
        issues.append({
            "code": "REGIME_FAILURE",
            "severity": severity,
            "msg": f"Regime failure — best: {best} ({regime_wr[best]:.0f}% WR)  worst: {worst} ({regime_wr[worst]:.0f}% WR)",
            "metric": "regime",
            "delta": -spread,
        })

    failing = [r for r, wr in regime_wr.items() if wr < 40]
    for r in failing:
        issues.append({
            "code": "REGIME_UNDERPERFORM",
            "severity": "INFO",
            "msg": f"Poor performance in {r} regime: {regime_wr[r]:.0f}% WR",
            "metric": "regime",
            "delta": 40 - regime_wr[r],
        })

    return issues


def _detect_confidence_failure(trades_all: list[dict]) -> list[dict]:
    issues = []
    if len(trades_all) < 10:
        return []

    sorted_by_conf = sorted(trades_all, key=lambda t: t.get("confidence", 0))
    n = len(sorted_by_conf)
    high_conf = sorted_by_conf[int(n * 0.6):]
    low_conf  = sorted_by_conf[:int(n * 0.4)]

    if not high_conf or not low_conf:
        return []

    def wr(group):
        wins = sum(1 for t in group if t.get("pnl", 0) > 0)
        return wins / len(group) * 100

    wr_high = wr(high_conf)
    wr_low  = wr(low_conf)
    delta   = wr_high - wr_low

    if delta < DECAY_THRESHOLDS["overconf_delta"]:
        issues.append({
            "code": "CONFIDENCE_MISCALIBRATION",
            "severity": "WARNING",
            "msg": f"High-confidence signals underperforming: high_conf={wr_high:.1f}%  low_conf={wr_low:.1f}%  ({delta:+.1f}pp)",
            "metric": "confidence",
            "delta": delta,
        })
    return issues


def _detect_signal_saturation(trades_all: list[dict], m30: dict, m90: dict) -> list[dict]:
    issues = []
    n30 = m30.get("trades", 0)
    n90 = m90.get("trades", 0)
    if n90 < 5 or n30 < 3:
        return []
    trades_per_month_30 = n30
    trades_per_month_90 = n90 / 3
    if trades_per_month_90 > 0:
        pct_increase = (trades_per_month_30 - trades_per_month_90) / trades_per_month_90 * 100
        if pct_increase > DECAY_THRESHOLDS["saturation_pct"]:
            issues.append({
                "code": "SIGNAL_SATURATION",
                "severity": "INFO",
                "msg": f"Signal frequency increasing {pct_increase:.0f}% — may be diluting edge quality",
                "metric": "saturation",
                "delta": pct_increase,
            })
    return issues


def _detect_volatility_sensitivity(trades_all: list[dict]) -> list[dict]:
    issues = []
    with_atr    = [t for t in trades_all if t.get("atr", 0) > 0]
    if len(with_atr) < 10:
        return []

    atrs    = sorted([t.get("atr", 0) for t in with_atr])
    median_atr = atrs[len(atrs) // 2]

    high_vol = [t for t in with_atr if t.get("atr", 0) > median_atr * 1.3]
    low_vol  = [t for t in with_atr if t.get("atr", 0) <= median_atr]

    if not high_vol or not low_vol:
        return []

    def wr(group):
        wins = sum(1 for t in group if t.get("pnl", 0) > 0)
        return wins / len(group) * 100

    wr_hi = wr(high_vol)
    wr_lo = wr(low_vol)
    delta = wr_hi - wr_lo

    if delta < -15:
        issues.append({
            "code": "VOLATILITY_SENSITIVITY",
            "severity": "WARNING",
            "msg": f"Performance collapses in high-volatility: HiVol={wr_hi:.1f}%  LoVol={wr_lo:.1f}%  ({delta:+.1f}pp)",
            "metric": "volatility",
            "delta": delta,
        })
    return issues


# ── Edge health score ────────────────────────────────────────────────────────────

_SEV_WEIGHTS = {"CRITICAL": 15, "WARNING": 7, "INFO": 2}

def compute_edge_health(issues: list[dict], m30: dict) -> int:
    """
    Score 0-100. Starts at 100, deducts for issues.
    Also rewards good recent performance.
    """
    score = 100
    for issue in issues:
        score -= _SEV_WEIGHTS.get(issue.get("severity", "INFO"), 2)

    wr30 = m30.get("win_rate", 50)
    pf30 = m30.get("profit_factor", 1)
    exp30 = m30.get("expectancy", 0)
    n30  = m30.get("trades", 0)

    if n30 < 5:
        score -= 10
    if wr30 < 45:
        score -= 10
    elif wr30 > 60:
        score += 5
    if pf30 < 1.0:
        score -= 15
    elif pf30 > 1.5:
        score += 5
    if exp30 < 0:
        score -= 10
    elif exp30 > 1:
        score += 5

    return max(0, min(100, score))


def edge_grade(score: int) -> str:
    for threshold, label in EDGE_GRADES:
        if score >= threshold:
            return label
    return "Critical Failure"


def edge_status(score: int) -> str:
    if score >= 90:
        return "INSTITUTIONAL GRADE"
    if score >= 75:
        return "STRONG EDGE"
    if score >= 60:
        return "EDGE DEGRADING"
    if score >= 40:
        return "EDGE WEAK"
    return "CRITICAL FAILURE"


# ── Recommendations engine ───────────────────────────────────────────────────────

def _generate_recommendations(issues: list[dict], stats: dict, strategy: str) -> list[str]:
    recs = []
    codes = {i["code"] for i in issues}

    if "WIN_RATE_DECAY" in codes or "WIN_RATE_COLLAPSE" in codes:
        recs.append("Increase minimum signal confidence filter to improve trade selectivity.")
    if "EXPECTANCY_COLLAPSE" in codes:
        recs.append("Review SL/TP ratios — expectancy collapse often signals widening stops without proportional gain.")
    if "PROFIT_FACTOR_DROP" in codes:
        recs.append("Tighten entry criteria: run /optimize to find best-performing parameter set.")
    if "DRAWDOWN_EXPANSION" in codes:
        recs.append("Reduce position exposure until drawdown stabilises below historical baseline.")
    if "REGIME_FAILURE" in codes:
        recs.append(f"Suppress {strategy.upper()} signals during ranging conditions — apply regime filter.")
    if "CONFIDENCE_MISCALIBRATION" in codes:
        recs.append("Recalibrate confidence scoring — high-confidence signals are not outperforming low-confidence ones.")
    if "SIGNAL_SATURATION" in codes:
        recs.append("Signal frequency is elevated — raise minimum threshold to preserve edge quality per trade.")
    if "VOLATILITY_SENSITIVITY" in codes:
        recs.append("Avoid trading during high-ATR sessions — apply ATR-based signal suppression filter.")

    if not recs:
        recs.append("No deterioration detected — monitor weekly for early trend changes.")

    return recs


# ── Full decay analysis runner ───────────────────────────────────────────────────

def run_decay_analysis(stats: dict[str, dict] | None = None) -> dict[str, dict]:
    """
    Run full decay analysis for all strategies.
    Returns dict: strategy_key → decay result dict.
    """
    from analytics.performance import get_performance_stats, _get_all_trades

    if stats is None:
        stats = get_performance_stats()

    all_trades = _get_all_trades()
    trades_by_strat: dict[str, list[dict]] = defaultdict(list)
    for t in all_trades:
        run_id = t.get("run_id")
        if run_id is None:
            continue
        with db._lock, db._conn() as c:
            row = c.execute("SELECT strategy FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
            if row:
                trades_by_strat[row["strategy"]].append(t)

    results: dict[str, dict] = {}

    for strat_key, s in stats.items():
        trades = trades_by_strat.get(strat_key, s.get("all_trades", []))

        m7  = _rolling_metrics(trades, 7)
        m30 = _rolling_metrics(trades, 30)
        m90 = _rolling_metrics(trades, 90)

        snap7  = _snapshots_rolling(strat_key, 7)
        snap30 = _snapshots_rolling(strat_key, 30)
        snap90 = _snapshots_rolling(strat_key, 90)

        def _merge(m, snap):
            if snap and snap.get("samples", 0) >= 3:
                return {
                    "trades":        m.get("trades", 0),
                    "win_rate":      snap.get("win_rate", m.get("win_rate", 0)),
                    "profit_factor": snap.get("profit_factor", m.get("profit_factor", 0)),
                    "expectancy":    snap.get("expectancy", m.get("expectancy", 0)),
                    "max_drawdown":  m.get("max_drawdown", 0),
                    "avg_confidence": m.get("avg_confidence", 0),
                }
            return m

        m7_f  = _merge(m7, snap7)
        m30_f = _merge(m30, snap30)
        m90_f = _merge(m90, snap90)

        issues = []
        issues.extend(_detect_win_rate_decay(m7_f, m30_f, m90_f))
        issues.extend(_detect_expectancy_decay(m30_f, m90_f))
        issues.extend(_detect_pf_deterioration(m30_f, m90_f))
        issues.extend(_detect_drawdown_expansion(m30_f, m90_f))
        issues.extend(_detect_regime_failure(trades))
        issues.extend(_detect_confidence_failure(trades))
        issues.extend(_detect_signal_saturation(trades, m30_f, m90_f))
        issues.extend(_detect_volatility_sensitivity(trades))

        sev_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        issues.sort(key=lambda x: sev_order.get(x.get("severity", "INFO"), 2))

        health = compute_edge_health(issues, m30_f)
        grade  = edge_grade(health)
        status = edge_status(health)
        recs   = _generate_recommendations(issues, s, strat_key)

        results[strat_key] = {
            "label":        s["label"],
            "strategy":     strat_key,
            "health":       health,
            "grade":        grade,
            "status":       status,
            "issues":       issues,
            "recommendations": recs,
            "m7":  m7_f,
            "m30": m30_f,
            "m90": m90_f,
            "trades": trades,
        }

    return results


# ── Text formatters ───────────────────────────────────────────────────────────────

def format_decay_report(decay: dict[str, dict], strategy: str | None = None) -> str:
    if not decay:
        return (
            "No decay data available.\n\n"
            "Run backtests first:\n"
            "/backtest fib 1H 30d\n"
            "/backtest smc 1H 30d"
        )

    targets = {strategy: decay[strategy]} if strategy and strategy in decay else decay
    lines = []

    for strat_key, d in targets.items():
        m7, m30, m90 = d["m7"], d["m30"], d["m90"]
        health = d["health"]
        bar = "█" * (health // 10) + "░" * (10 - health // 10)

        lines.append(f"[ {d['label']} ] — Edge Health: {health}/100")
        lines.append(f"  [{bar}]  {d['grade']}")
        lines.append(f"  Status: {d['status']}")
        lines.append("")
        lines.append("  Rolling Metrics:")
        lines.append(f"  {'Metric':<18} {'7d':>8} {'30d':>8} {'90d':>8}")
        lines.append(f"  {'Win Rate %':<18} {m7.get('win_rate',0):>7.1f}% {m30.get('win_rate',0):>7.1f}% {m90.get('win_rate',0):>7.1f}%")
        lines.append(f"  {'Profit Factor':<18} {m7.get('profit_factor',0):>8.2f} {m30.get('profit_factor',0):>8.2f} {m90.get('profit_factor',0):>8.2f}")
        lines.append(f"  {'Expectancy':<18} {m7.get('expectancy',0):>+8.3f} {m30.get('expectancy',0):>+8.3f} {m90.get('expectancy',0):>+8.3f}")
        lines.append(f"  {'Max Drawdown':<18} {m7.get('max_drawdown',0):>8.2f} {m30.get('max_drawdown',0):>8.2f} {m90.get('max_drawdown',0):>8.2f}")
        lines.append(f"  {'Trades':<18} {m7.get('trades',0):>8} {m30.get('trades',0):>8} {m90.get('trades',0):>8}")
        lines.append("")

        issues = d.get("issues", [])
        sev_icon = {"CRITICAL": "✗", "WARNING": "!", "INFO": "i"}

        if issues:
            lines.append("  Warnings Detected:")
            for issue in issues[:6]:
                icon = sev_icon.get(issue.get("severity"), "?")
                lines.append(f"  {icon} {issue['msg']}")
        else:
            lines.append("  No deterioration detected")
        lines.append("")

        recs = d.get("recommendations", [])
        if recs:
            lines.append("  Recommendations:")
            for rec in recs[:3]:
                lines.append(f"  → {rec}")
        lines.append("")

    return "\n".join(lines)


def format_edge_summary(decay: dict[str, dict]) -> str:
    """Compact one-liner edge health summary for all strategies."""
    if not decay:
        return "No edge data — run /backtest first."

    lines = ["Edge Health Summary", "=" * 28, ""]
    sorted_items = sorted(decay.items(), key=lambda x: -x[1]["health"])

    for strat_key, d in sorted_items:
        h = d["health"]
        bar = "█" * (h // 10) + "░" * (10 - h // 10)
        n_crit = sum(1 for i in d["issues"] if i.get("severity") == "CRITICAL")
        n_warn = sum(1 for i in d["issues"] if i.get("severity") == "WARNING")
        flag = ""
        if n_crit > 0:
            flag = f"  [{n_crit} critical]"
        elif n_warn > 0:
            flag = f"  [{n_warn} warnings]"

        lines.append(f"{d['label']}")
        lines.append(f"  [{bar}] {h}/100  {d['grade']}{flag}")
        lines.append("")

    return "\n".join(lines)


# ── Chart generators ─────────────────────────────────────────────────────────────

def _style_ax(ax) -> None:
    ax.set_facecolor(DARK_BG)
    ax.tick_params(colors=TEXT_CLR, labelsize=6.5)
    for sp in ax.spines.values():
        sp.set_color(GRID_CLR)
    ax.yaxis.label.set_color(TEXT_CLR)
    ax.xaxis.label.set_color(TEXT_CLR)
    ax.grid(axis="y", color=GRID_CLR, linewidth=0.4, alpha=0.5)


def generate_decay_chart(decay: dict[str, dict]) -> io.BytesIO:
    """Rolling win rate curves for all strategies."""
    if not decay:
        return _empty_chart("No decay data")

    fig = plt.figure(figsize=(7.5, 8.5), facecolor=DARK_BG)
    gs  = gridspec.GridSpec(3, 2, hspace=0.5, wspace=0.38)

    ax_wr   = fig.add_subplot(gs[0, :])
    ax_exp  = fig.add_subplot(gs[1, 0])
    ax_pf   = fig.add_subplot(gs[1, 1])
    ax_dd   = fig.add_subplot(gs[2, 0])
    ax_hlth = fig.add_subplot(gs[2, 1])

    for ax in (ax_wr, ax_exp, ax_pf, ax_dd, ax_hlth):
        _style_ax(ax)

    windows = [7, 30, 90]
    for i, (strat_key, d) in enumerate(decay.items()):
        clr = COLORS[i % len(COLORS)]
        wrs   = [d["m7"].get("win_rate", 0), d["m30"].get("win_rate", 0), d["m90"].get("win_rate", 0)]
        exps  = [d["m7"].get("expectancy", 0), d["m30"].get("expectancy", 0), d["m90"].get("expectancy", 0)]
        pfs   = [d["m7"].get("profit_factor", 0), d["m30"].get("profit_factor", 0), d["m90"].get("profit_factor", 0)]
        dds   = [d["m7"].get("max_drawdown", 0), d["m30"].get("max_drawdown", 0), d["m90"].get("max_drawdown", 0)]

        ax_wr.plot(windows, wrs, color=clr, marker="o", ms=4, linewidth=1.5,
                   label=d["label"])
        ax_exp.plot(windows, exps, color=clr, marker="o", ms=3.5, linewidth=1.3)
        ax_pf.plot(windows, pfs,  color=clr, marker="o", ms=3.5, linewidth=1.3,
                   label=d["label"])
        ax_dd.plot(windows, dds,  color=clr, marker="o", ms=3.5, linewidth=1.3)

    ax_wr.axhline(50, color=WARN_CLR, linewidth=0.8, linestyle="--", alpha=0.7)
    ax_wr.set_title("Win Rate — Rolling", color=TEXT_CLR, fontsize=8.5, fontweight="bold")
    ax_wr.set_xlabel("Lookback (days)", color=TEXT_CLR, fontsize=7)
    ax_wr.set_ylabel("Win Rate %", color=TEXT_CLR, fontsize=7)
    ax_wr.set_xticks([7, 30, 90]); ax_wr.set_xticklabels(["7d", "30d", "90d"])
    ax_wr.legend(fontsize=6.5, facecolor=DARK_BG, labelcolor=TEXT_CLR, loc="best", framealpha=0.6)

    ax_exp.axhline(0, color=FLAT_CLR, linewidth=0.7, linestyle="--")
    ax_exp.set_title("Expectancy", color=TEXT_CLR, fontsize=8, fontweight="bold")
    ax_exp.set_xticks([7, 30, 90]); ax_exp.set_xticklabels(["7d", "30d", "90d"])

    ax_pf.axhline(1.0, color=WARN_CLR, linewidth=0.7, linestyle="--", alpha=0.7)
    ax_pf.set_title("Profit Factor", color=TEXT_CLR, fontsize=8, fontweight="bold")
    ax_pf.set_xticks([7, 30, 90]); ax_pf.set_xticklabels(["7d", "30d", "90d"])

    ax_dd.set_title("Max Drawdown", color=TEXT_CLR, fontsize=8, fontweight="bold")
    ax_dd.set_xticks([7, 30, 90]); ax_dd.set_xticklabels(["7d", "30d", "90d"])

    labels = [d["label"] for d in decay.values()]
    scores = [d["health"] for d in decay.values()]
    clrs_h = [
        BULL_CLR if h >= 75 else (WARN_CLR if h >= 50 else BEAR_CLR)
        for h in scores
    ]
    bars = ax_hlth.barh(range(len(scores)), scores, color=clrs_h, height=0.55)
    ax_hlth.set_yticks(range(len(scores)))
    ax_hlth.set_yticklabels(labels, fontsize=7)
    ax_hlth.set_xlim(0, 100)
    ax_hlth.axvline(60, color=WARN_CLR, linewidth=0.7, linestyle="--", alpha=0.6)
    ax_hlth.set_title("Edge Health Score", color=TEXT_CLR, fontsize=8, fontweight="bold")
    for bar, val in zip(bars, scores):
        ax_hlth.text(val + 0.5, bar.get_y() + bar.get_height() / 2,
                     f"{val}", va="center", fontsize=6.5, color=TEXT_CLR)

    fig.suptitle("XAUUSD  Strategy Decay Monitor", color=TEXT_CLR, fontsize=10,
                 fontweight="bold", y=0.99)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_regime_radar(decay: dict[str, dict]) -> io.BytesIO:
    """Regime performance radar chart."""
    from analytics.performance import get_performance_stats

    all_stats = get_performance_stats()
    regimes = ["Trending", "Ranging", "Volatile", "Compression", "Expansion"]
    n_reg   = len(regimes)

    strats = list(all_stats.keys())
    if not strats:
        return _empty_chart("No regime data")

    angles = [n / n_reg * 2 * math.pi for n in range(n_reg)]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(5.5, 5.5), subplot_kw={"polar": True}, facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    ax.tick_params(colors=TEXT_CLR, labelsize=6)
    ax.set_rlabel_position(30)
    ax.grid(color=GRID_CLR, linewidth=0.5)
    ax.spines["polar"].set_color(GRID_CLR)

    for i, strat_key in enumerate(strats[:4]):
        s = all_stats[strat_key]
        regime_stats = s.get("regime_stats", {})
        values = []
        for reg in regimes:
            wr = regime_stats.get(reg, {}).get("win_rate", 50)
            values.append(wr)
        values += values[:1]

        clr = COLORS[i % len(COLORS)]
        ax.plot(angles, values, color=clr, linewidth=1.5, label=s["label"])
        ax.fill(angles, values, alpha=0.08, color=clr)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(regimes, fontsize=7, color=TEXT_CLR)
    ax.set_ylim(0, 100)
    ax.set_rticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], fontsize=5.5, color=FLAT_CLR)

    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=7,
              facecolor=DARK_BG, labelcolor=TEXT_CLR)
    ax.set_title("Regime Performance Radar", color=TEXT_CLR, fontsize=9,
                 fontweight="bold", pad=15)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_confidence_calibration_chart(decay: dict[str, dict]) -> io.BytesIO:
    """Chart: confidence bins vs actual win rate per strategy."""
    from analytics.performance import _get_all_trades

    all_trades = _get_all_trades()
    bins = [(0, 25), (25, 45), (45, 60), (60, 75), (75, 100)]
    bin_labels = ["0-25%", "25-45%", "45-60%", "60-75%", "75-100%"]

    strats_data: dict[str, list[float]] = {}
    for strat_key in decay:
        strat_trades = [t for t in all_trades]
        bin_wrs = []
        for lo, hi in bins:
            bucket = [t for t in strat_trades if lo <= t.get("confidence", 0) < hi]
            if bucket:
                wins = sum(1 for t in bucket if t.get("pnl", 0) > 0)
                bin_wrs.append(wins / len(bucket) * 100)
            else:
                bin_wrs.append(0)
        strats_data[strat_key] = bin_wrs

    if not strats_data:
        return _empty_chart("No confidence data")

    fig, ax = plt.subplots(figsize=(6.5, 3.5), facecolor=DARK_BG)
    _style_ax(ax)
    ax.grid(axis="y", color=GRID_CLR, linewidth=0.4, alpha=0.5)

    ideal_x = [12.5, 35, 52.5, 67.5, 87.5]
    ideal_y = [40, 48, 55, 62, 70]
    ax.plot(range(len(bins)), ideal_y, color=FLAT_CLR, linewidth=0.8,
            linestyle=":", label="Ideal calibration", alpha=0.7)

    for i, (strat_key, wrs) in enumerate(strats_data.items()):
        label = decay[strat_key]["label"] if strat_key in decay else strat_key.title()
        ax.plot(range(len(bins)), wrs, color=COLORS[i % len(COLORS)], marker="o",
                ms=4, linewidth=1.4, label=label)

    ax.axhline(50, color=WARN_CLR, linewidth=0.8, linestyle="--", alpha=0.6)
    ax.set_xticks(range(len(bins)))
    ax.set_xticklabels(bin_labels, fontsize=6.5)
    ax.set_ylabel("Actual Win Rate %", color=TEXT_CLR, fontsize=7)
    ax.set_xlabel("Confidence Bin", color=TEXT_CLR, fontsize=7)
    ax.set_title("Confidence Calibration — Signal Quality by Confidence Level",
                 color=TEXT_CLR, fontsize=8.5, fontweight="bold")
    ax.legend(fontsize=6.5, facecolor=DARK_BG, labelcolor=TEXT_CLR, framealpha=0.6)
    ax.set_ylim(0, 100)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


def _empty_chart(msg: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(5.5, 2.5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG); ax.axis("off")
    ax.text(0.5, 0.5, msg, ha="center", va="center", color=TEXT_CLR, fontsize=9)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf
