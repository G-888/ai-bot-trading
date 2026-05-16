"""
analytics/diagnostics.py — Strategy health diagnostics engine.

Detects: overfitting, low sample size, regime dependency,
         unstable confidence, weak RR, excessive drawdown,
         timeframe conflicts, and strategy decay.

Python-only. No mocked data.
"""
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

MIN_SAMPLE_WARN  = 20
MIN_SAMPLE_ERR   = 8
OVERFIT_DELTA    = 15.0
MAX_DD_PCT_WARN  = 0.5
MAX_DD_PCT_ERR   = 1.0
MIN_PF_WARN      = 1.2
MIN_PF_ERR       = 1.0
MIN_RR_WARN      = 1.0
DECAY_DELTA      = 10.0


SEVERITY = {"INFO": 0, "WARN": 1, "ERROR": 2}


def _issue(severity: str, code: str, msg: str, detail: str = "") -> dict:
    return {"severity": severity, "code": code, "message": msg, "detail": detail}


# ── Individual diagnostic checks ─────────────────────────────────────────────────

def check_sample_size(stats: dict) -> list[dict]:
    issues = []
    n = stats.get("total_trades", 0)
    if n < MIN_SAMPLE_ERR:
        issues.append(_issue("ERROR", "LOW_SAMPLE",
            f"Sample too small ({n} trades) — results unreliable",
            f"Need ≥{MIN_SAMPLE_ERR} trades minimum for any validity."))
    elif n < MIN_SAMPLE_WARN:
        issues.append(_issue("WARN", "SMALL_SAMPLE",
            f"Small sample ({n} trades) — interpret cautiously",
            f"Recommend ≥{MIN_SAMPLE_WARN} trades for statistical confidence."))
    return issues


def check_overfitting(stats: dict) -> list[dict]:
    issues = []
    wr_full = stats.get("win_rate", 0)
    wr_30   = stats.get("rolling_30d_wr", 0)
    wr_90   = stats.get("rolling_90d_wr", 0)
    delta_30_90 = abs(wr_30 - wr_90)
    delta_full  = abs(wr_full - wr_30)

    if delta_30_90 > OVERFIT_DELTA:
        issues.append(_issue("WARN", "UNSTABLE_WR",
            f"Win rate unstable: 30d={wr_30:.1f}% vs 90d={wr_90:.1f}%",
            "Large delta may indicate regime sensitivity or insufficient robustness."))
    if delta_full > OVERFIT_DELTA * 1.5:
        issues.append(_issue("ERROR", "OVERFIT_RISK",
            f"Possible overfitting: overall WR={wr_full:.1f}% vs 30d={wr_30:.1f}%",
            "Strategy may be curve-fitted to historical data."))
    return issues


def check_drawdown(stats: dict) -> list[dict]:
    issues = []
    dd  = stats.get("max_drawdown", 0)
    pnl = abs(stats.get("total_pnl", 0.001))
    if pnl == 0:
        return issues
    ratio = dd / pnl
    if ratio >= MAX_DD_PCT_ERR:
        issues.append(_issue("ERROR", "EXCESS_DRAWDOWN",
            f"Excessive drawdown: DD={dd:.2f} ({ratio:.0%} of gross PnL)",
            "Risk of ruin is elevated. Review position sizing and SL placement."))
    elif ratio >= MAX_DD_PCT_WARN:
        issues.append(_issue("WARN", "HIGH_DRAWDOWN",
            f"High drawdown: DD={dd:.2f} ({ratio:.0%} of gross PnL)",
            "Drawdown is elevated relative to returns. Monitor closely."))
    return issues


def check_profit_factor(stats: dict) -> list[dict]:
    issues = []
    pf = stats.get("profit_factor", 0)
    if pf < MIN_PF_ERR:
        issues.append(_issue("ERROR", "NEGATIVE_EDGE",
            f"Profit factor {pf:.2f} — strategy has no positive edge",
            "Expected PF ≥1.0 for profitability."))
    elif pf < MIN_PF_WARN:
        issues.append(_issue("WARN", "WEAK_EDGE",
            f"Profit factor {pf:.2f} — edge is marginal",
            "Target PF ≥1.5 for robust institutional-grade strategies."))
    return issues


def check_rr_profile(stats: dict) -> list[dict]:
    issues = []
    avg_rr = stats.get("avg_rr", 0)
    if avg_rr < MIN_RR_WARN:
        issues.append(_issue("WARN", "WEAK_RR",
            f"Avg RR {avg_rr:.2f} — below 1:1 risk/reward",
            "Low RR requires exceptionally high win rate to be profitable."))
    return issues


def check_regime_dependency(stats: dict) -> list[dict]:
    issues = []
    regime_stats = stats.get("regime_stats", {})
    if not regime_stats:
        return issues

    viable = [(r, rd) for r, rd in regime_stats.items() if rd["trades"] >= 5]
    if not viable:
        return issues

    win_rates = [rd["win_rate"] for _, rd in viable]
    if not win_rates:
        return issues
    spread = max(win_rates) - min(win_rates)

    if spread > 30:
        best_regime = max(viable, key=lambda x: x[1]["win_rate"])[0]
        worst_regime = min(viable, key=lambda x: x[1]["win_rate"])[0]
        issues.append(_issue("WARN", "REGIME_DEPENDENT",
            f"Regime performance spread: {spread:.0f}% (best: {best_regime}, worst: {worst_regime})",
            "Strategy shows strong regime bias. Tune regime filters or weight adjustments."))

    losing_regimes = [r for r, rd in viable if rd["win_rate"] < 40]
    if losing_regimes:
        issues.append(_issue("INFO", "REGIME_LOSERS",
            f"Underperforming in: {', '.join(losing_regimes)}",
            "Consider suppressing signals in these market regimes."))
    return issues


def check_confidence_stability(stats: dict) -> list[dict]:
    issues = []
    avg_conf = stats.get("avg_confidence", 0)
    wr       = stats.get("win_rate", 0)

    if avg_conf > 65 and wr < 45:
        issues.append(_issue("ERROR", "CONFIDENCE_OVERSTATE",
            f"Confidence overestimates edge: avg_conf={avg_conf:.0f}% vs win_rate={wr:.1f}%",
            "The confidence model is not predictive. Recalibrate scoring thresholds."))
    elif avg_conf < 35 and wr > 55:
        issues.append(_issue("INFO", "CONFIDENCE_UNDERSTATE",
            f"Confidence may be conservative: avg_conf={avg_conf:.0f}% vs win_rate={wr:.1f}%",
            "Consider relaxing signal confidence thresholds."))
    return issues


def check_strategy_decay(stats: dict) -> list[dict]:
    issues = []
    wr_30 = stats.get("rolling_30d_wr", 0)
    wr_90 = stats.get("rolling_90d_wr", 0)

    if wr_90 > 0 and (wr_90 - wr_30) > DECAY_DELTA:
        issues.append(_issue("WARN", "STRATEGY_DECAY",
            f"Decay detected: 30d WR={wr_30:.1f}% vs 90d WR={wr_90:.1f}%",
            "Recent performance is significantly worse than historical. Strategy may be losing edge."))
    return issues


# ── Full diagnostics runner ───────────────────────────────────────────────────────

def run_diagnostics(stats: dict[str, dict] | None = None) -> dict[str, list[dict]]:
    """
    Run all diagnostic checks for each strategy.
    Returns: dict[strategy_key] → list of issue dicts
    """
    from analytics.performance import get_performance_stats
    if stats is None:
        stats = get_performance_stats()

    all_issues: dict[str, list[dict]] = {}
    for strat_key, s in stats.items():
        issues = []
        issues.extend(check_sample_size(s))
        issues.extend(check_overfitting(s))
        issues.extend(check_drawdown(s))
        issues.extend(check_profit_factor(s))
        issues.extend(check_rr_profile(s))
        issues.extend(check_regime_dependency(s))
        issues.extend(check_confidence_stability(s))
        issues.extend(check_strategy_decay(s))

        issues.sort(key=lambda x: -SEVERITY.get(x["severity"], 0))
        all_issues[strat_key] = issues

    return all_issues


def format_diagnostics_text(all_issues: dict[str, list[dict]], stats: dict[str, dict]) -> str:
    if not all_issues:
        return (
            "No diagnostic data.\n\n"
            "Run backtests first:\n"
            "/backtest fib 1H 30d"
        )

    sev_icon = {"ERROR": "✗", "WARN": "!", "INFO": "i"}
    lines = ["Strategy Diagnostics", "=" * 30, ""]

    for strat_key, issues in all_issues.items():
        label = stats.get(strat_key, {}).get("label", strat_key.title())
        n_err  = sum(1 for i in issues if i["severity"] == "ERROR")
        n_warn = sum(1 for i in issues if i["severity"] == "WARN")

        status = "PASS" if n_err == 0 and n_warn == 0 else (
            f"{n_err} error(s), {n_warn} warning(s)"
        )

        lines.append(f"[ {label} ]  {status}")

        if not issues:
            lines.append("  No issues detected")
        else:
            for issue in issues[:8]:
                icon = sev_icon.get(issue["severity"], "?")
                lines.append(f"  {icon} [{issue['code']}]")
                lines.append(f"    {issue['message']}")
                if issue.get("detail"):
                    detail_short = issue["detail"][:80]
                    lines.append(f"    → {detail_short}")
        lines.append("")

    return "\n".join(lines)
