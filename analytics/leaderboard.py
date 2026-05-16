"""
analytics/leaderboard.py — Strategy ranking and leaderboard engine.

Ranks strategies using real historical backtest data from SQLite.
All scoring is Python-computed. AI only explains outputs.
"""
import io
import logging
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analytics.performance import get_performance_stats, _style_ax

logger = logging.getLogger(__name__)

DARK_BG  = "#0d1117"
TEXT_CLR = "#e2e8f0"
COLORS   = ["#ffd700", "#c0c0c0", "#cd7f32", "#63b3ed", "#b794f4", "#76e4f7"]
FLAT_CLR = "#4a5568"
BULL_CLR = "#00c896"
BEAR_CLR = "#ff4560"
WARN_CLR = "#f6ad55"

RANK_MEDALS = ["1st", "2nd", "3rd", "4th", "5th", "6th"]


# ── Scoring dimensions ──────────────────────────────────────────────────────────

def _score_consistency(stats: dict) -> float:
    """
    Consistency = stability of win rate across rolling windows.
    Measures how close 30d and 90d win rates are.
    Max 25 pts.
    """
    wr  = stats.get("win_rate", 0)
    r30 = stats.get("rolling_30d_wr", 0)
    r90 = stats.get("rolling_90d_wr", 0)
    delta = abs(r30 - r90)
    base  = min(wr / 100 * 15, 15)
    stability_bonus = max(0, (1.0 - delta / 30) * 10)
    return round(min(base + stability_bonus, 25), 2)


def _score_expectancy(stats: dict) -> float:
    """
    Expectancy contribution. Max 25 pts.
    """
    exp = stats.get("expectancy", 0)
    if exp <= 0:
        return 0.0
    return round(min(exp / 5.0 * 25, 25), 2)


def _score_drawdown_control(stats: dict) -> float:
    """
    Drawdown control. Lower DD relative to total PnL = better. Max 20 pts.
    """
    dd  = stats.get("max_drawdown", 0)
    pnl = abs(stats.get("total_pnl", 0.001))
    if pnl == 0:
        return 0.0
    ratio = dd / pnl
    if ratio < 0.3:
        pts = 20
    elif ratio < 0.6:
        pts = 15
    elif ratio < 1.0:
        pts = 10
    elif ratio < 2.0:
        pts = 5
    else:
        pts = 0
    return float(pts)


def _score_regime_adaptability(stats: dict) -> float:
    """
    Regime adaptability = how many regimes have positive win rate.
    Max 15 pts.
    """
    regime_stats = stats.get("regime_stats", {})
    if not regime_stats:
        return 5.0
    positive = sum(1 for rd in regime_stats.values() if rd.get("win_rate", 0) >= 50 and rd["trades"] >= 3)
    total    = sum(1 for rd in regime_stats.values() if rd["trades"] >= 3)
    if total == 0:
        return 5.0
    return round(positive / total * 15, 2)


def _score_signal_quality(stats: dict) -> float:
    """
    Signal quality = Sharpe × profit factor × sample confidence.
    Max 15 pts.
    """
    sharpe = stats.get("sharpe", 0)
    pf     = min(stats.get("profit_factor", 0), 5.0)
    n      = stats.get("total_trades", 0)
    sample_conf = min(n / 30, 1.0)

    sharpe_norm = min(max(sharpe, 0), 3.0) / 3.0
    pf_norm     = pf / 5.0
    return round((sharpe_norm * 0.5 + pf_norm * 0.5) * sample_conf * 15, 2)


# ── Composite scores ─────────────────────────────────────────────────────────────

def _edge_rating(total_score: float) -> str:
    if total_score >= 80:
        return "Institutional Edge"
    if total_score >= 65:
        return "Strong Edge"
    if total_score >= 50:
        return "Moderate Edge"
    if total_score >= 35:
        return "Weak Edge"
    return "No Edge"


def _stability_rating(consistency: float, dd_score: float) -> str:
    combined = consistency + dd_score
    if combined >= 38:
        return "Very Stable"
    if combined >= 28:
        return "Stable"
    if combined >= 18:
        return "Moderate"
    return "Unstable"


def _confidence_reliability(stats: dict) -> str:
    avg_conf = stats.get("avg_confidence", 0)
    wr       = stats.get("win_rate", 0)
    if avg_conf > 60 and wr > 55:
        return "High — confidence tracks performance"
    if avg_conf > 40 and wr > 45:
        return "Moderate — reasonable alignment"
    if avg_conf > 60 and wr < 45:
        return "Low — confidence overestimates edge"
    return "Weak — insufficient sample data"


# ── Leaderboard builder ──────────────────────────────────────────────────────────

def build_leaderboard(stats: dict[str, dict] | None = None) -> list[dict]:
    """
    Build a ranked leaderboard from performance stats.
    Returns list of rank dicts sorted by total_score desc.
    """
    if stats is None:
        stats = get_performance_stats()

    if not stats:
        return []

    scored = []
    for strat_key, s in stats.items():
        if s.get("total_trades", 0) < 1:
            continue

        cons  = _score_consistency(s)
        exp   = _score_expectancy(s)
        dd    = _score_drawdown_control(s)
        regime = _score_regime_adaptability(s)
        qual  = _score_signal_quality(s)
        total = cons + exp + dd + regime + qual

        scored.append({
            "strategy":            strat_key,
            "label":               s["label"],
            "total_score":         round(total, 2),
            "score_consistency":   cons,
            "score_expectancy":    exp,
            "score_drawdown":      dd,
            "score_regime":        regime,
            "score_quality":       qual,
            "edge_rating":         _edge_rating(total),
            "stability_rating":    _stability_rating(cons, dd),
            "confidence_reliability": _confidence_reliability(s),
            "win_rate":            s["win_rate"],
            "profit_factor":       s["profit_factor"],
            "expectancy":          s["expectancy"],
            "max_drawdown":        s["max_drawdown"],
            "total_trades":        s["total_trades"],
            "vol_adj_score":       s["vol_adj_score"],
        })

    scored.sort(key=lambda x: -x["total_score"])
    return scored


def format_leaderboard_text(ranked: list[dict]) -> str:
    if not ranked:
        return (
            "No backtest data to rank.\n\n"
            "Run backtests first:\n"
            "/backtest fib 1H 30d\n"
            "/backtest smc 1H 30d\n"
            "/backtest confluence 1H 30d"
        )

    lines = ["Strategy Leaderboard", "=" * 30, ""]

    for i, entry in enumerate(ranked):
        medal = RANK_MEDALS[i] if i < len(RANK_MEDALS) else f"{i + 1}th"
        pf_str = f"{entry['profit_factor']:.2f}" if entry['profit_factor'] < 100 else "∞"
        score_bar = "█" * int(entry["total_score"] // 10) + "░" * (10 - int(entry["total_score"] // 10))

        lines.append(f"{medal}  {entry['label']}")
        lines.append(f"  Score:       [{score_bar}] {entry['total_score']:.1f}/100")
        lines.append(f"  Edge:        {entry['edge_rating']}")
        lines.append(f"  Stability:   {entry['stability_rating']}")
        lines.append(f"  Confidence:  {entry['confidence_reliability']}")
        lines.append(f"  Win Rate:    {entry['win_rate']:.1f}%")
        lines.append(f"  PF:          {pf_str}")
        lines.append(f"  Expectancy:  {entry['expectancy']:+.3f}")
        lines.append(f"  Max DD:      {entry['max_drawdown']:.2f}")
        lines.append(f"  Subscores:")
        lines.append(f"    Consistency  {entry['score_consistency']:.1f}/25")
        lines.append(f"    Expectancy   {entry['score_expectancy']:.1f}/25")
        lines.append(f"    DD Control   {entry['score_drawdown']:.1f}/20")
        lines.append(f"    Regime Fit   {entry['score_regime']:.1f}/15")
        lines.append(f"    Signal Qual  {entry['score_quality']:.1f}/15")
        lines.append("")

    return "\n".join(lines)


def generate_leaderboard_chart(ranked: list[dict]) -> io.BytesIO:
    """Generate leaderboard bar chart."""
    if not ranked:
        return _empty_chart("No data — run /backtest first")

    labels = [r["label"] for r in ranked]
    scores = [r["total_score"] for r in ranked]
    clrs   = [COLORS[i % len(COLORS)] for i in range(len(ranked))]

    fig, ax = plt.subplots(figsize=(7, 3.5), facecolor=DARK_BG)
    _style_ax(ax)

    bars = ax.barh(range(len(ranked)), scores, color=clrs, height=0.6, zorder=3)
    ax.set_yticks(range(len(ranked)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0, 100)
    ax.axvline(50, color=FLAT_CLR, linewidth=0.7, linestyle="--", alpha=0.7)
    ax.set_title("Strategy Leaderboard — Composite Score",
                 color=TEXT_CLR, fontsize=9.5, fontweight="bold")
    ax.set_xlabel("Score / 100", color=TEXT_CLR, fontsize=7.5)

    for bar, score, entry in zip(bars, scores, ranked):
        ax.text(
            score + 0.5, bar.get_y() + bar.get_height() / 2,
            f"{score:.1f}  {entry['edge_rating']}",
            va="center", fontsize=6.5, color=TEXT_CLR,
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


def _empty_chart(msg: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6, 2.5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG); ax.axis("off")
    ax.text(0.5, 0.5, msg, ha="center", va="center", color=TEXT_CLR, fontsize=9)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf
