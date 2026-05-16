"""
signals/heatmap.py — Multi-Timeframe Strategy Heatmap Engine.

Generates a matrix of strategy signals across 15m / 1H / 4H / Daily.
Python computes all values. AI only explains the output.
"""
import io
import logging
from datetime import datetime, timezone

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from market.data import fetch_ohlcv
from market.regime import detect_regime
from strategies.fibonacci import run_fibonacci_analysis
from strategies.smc import run_smc_analysis
from strategies.session import analyze_session
from market.indicators import rsi as rsi_indicator, ema, atr

logger = logging.getLogger(__name__)

TIMEFRAMES = {
    "15m": {"period": "5d",  "interval": "15m"},
    "1H":  {"period": "5d",  "interval": "1h"},
    "4H":  {"period": "30d", "interval": "4h"},
    "D1":  {"period": "90d", "interval": "1d"},
}

STRATEGIES = ["SMC", "Fibonacci", "Momentum", "Session"]

VOTE_UP   = "UP"
VOTE_DOWN = "DOWN"
VOTE_FLAT = "FLAT"


# ── Per-strategy, per-timeframe signal extraction ───────────────────────────────

def _smc_signal(df: pd.DataFrame) -> str:
    try:
        result = run_smc_analysis(df)
        bias = result.get("overall_bias", "Neutral")
        if "Bullish" in bias:
            return VOTE_UP
        if "Bearish" in bias:
            return VOTE_DOWN
        return VOTE_FLAT
    except Exception:
        return VOTE_FLAT


def _fib_signal(df: pd.DataFrame) -> str:
    try:
        result = run_fibonacci_analysis(df)
        if result is None:
            return VOTE_FLAT
        direction = result.get("direction", "")
        conf = result.get("confluence_score", 0)
        if conf < 20:
            return VOTE_FLAT
        if "retracement_up" in direction:
            return VOTE_UP
        if "retracement_down" in direction:
            return VOTE_DOWN
        return VOTE_FLAT
    except Exception:
        return VOTE_FLAT


def _momentum_signal(df: pd.DataFrame) -> str:
    try:
        if len(df) < 25:
            return VOTE_FLAT
        closes = df["Close"]
        ema9   = ema(closes, 9)
        ema21  = ema(closes, 21)
        rsi_s  = rsi_indicator(closes, 14)

        fast = float(ema9.iloc[-1])
        slow = float(ema21.iloc[-1])
        rsi_val = float(rsi_s.iloc[-1])

        if fast > slow and rsi_val > 52:
            return VOTE_UP
        if fast < slow and rsi_val < 48:
            return VOTE_DOWN
        return VOTE_FLAT
    except Exception:
        return VOTE_FLAT


def _session_signal(df: pd.DataFrame) -> str:
    try:
        closes = df["Close"]
        if len(closes) < 6:
            return VOTE_FLAT
        recent_close = float(closes.iloc[-1])
        prev_close   = float(closes.iloc[-6])
        pct = (recent_close - prev_close) / prev_close * 100
        if pct > 0.15:
            return VOTE_UP
        if pct < -0.15:
            return VOTE_DOWN
        return VOTE_FLAT
    except Exception:
        return VOTE_FLAT


SIGNAL_FNS = {
    "SMC":       _smc_signal,
    "Fibonacci": _fib_signal,
    "Momentum":  _momentum_signal,
    "Session":   _session_signal,
}


# ── Data fetching with cache ─────────────────────────────────────────────────────

_df_cache: dict[str, tuple[pd.DataFrame, float]] = {}
_CACHE_TTL = 300


def _get_df(tf_key: str) -> pd.DataFrame | None:
    import time
    now = time.time()
    if tf_key in _df_cache:
        df_cached, ts = _df_cache[tf_key]
        if now - ts < _CACHE_TTL:
            return df_cached

    cfg = TIMEFRAMES[tf_key]
    df = fetch_ohlcv(cfg["period"], cfg["interval"])
    if df is not None:
        _df_cache[tf_key] = (df, now)
    return df


# ── Matrix computation ───────────────────────────────────────────────────────────

def compute_heatmap() -> dict:
    """
    Compute the full multi-timeframe strategy matrix.

    Returns:
        matrix: dict[strategy][timeframe] = signal (UP/DOWN/FLAT)
        regimes: dict[timeframe] = regime dict
        alignment: dict — overall alignment summary
        conflict_score: float 0-1 (1 = full conflict)
        strongest_tf: str — timeframe with strongest consensus
        trend_agreement_score: float 0-100
        warnings: list[str]
        timestamp: str
    """
    matrix: dict[str, dict[str, str]] = {s: {} for s in STRATEGIES}
    regimes: dict[str, dict] = {}
    warnings: list[str] = []

    for tf_key in TIMEFRAMES:
        df = _get_df(tf_key)
        if df is None or df.empty:
            warnings.append(f"No data for {tf_key}")
            for s in STRATEGIES:
                matrix[s][tf_key] = VOTE_FLAT
            regimes[tf_key] = {"regime": "UNKNOWN", "label": "Unknown"}
            continue

        regimes[tf_key] = detect_regime(df)
        for strat, fn in SIGNAL_FNS.items():
            matrix[strat][tf_key] = fn(df)

    tf_list = list(TIMEFRAMES.keys())

    tf_scores: dict[str, float] = {}
    for tf in tf_list:
        ups   = sum(1 for s in STRATEGIES if matrix[s][tf] == VOTE_UP)
        downs = sum(1 for s in STRATEGIES if matrix[s][tf] == VOTE_DOWN)
        total = len(STRATEGIES)
        agreement = abs(ups - downs) / total
        tf_scores[tf] = agreement

    strongest_tf = max(tf_scores, key=lambda k: tf_scores[k])

    all_signals = [matrix[s][tf] for s in STRATEGIES for tf in tf_list]
    all_ups   = all_signals.count(VOTE_UP)
    all_downs = all_signals.count(VOTE_DOWN)
    all_total = len(all_signals)

    if all_total == 0:
        trend_agreement_score = 0.0
        conflict_score = 1.0
        overall_bias = VOTE_FLAT
    else:
        dominant = max(all_ups, all_downs)
        trend_agreement_score = round(dominant / all_total * 100, 1)
        conflict_score = round(1.0 - dominant / all_total, 3)
        overall_bias = VOTE_UP if all_ups > all_downs else (VOTE_DOWN if all_downs > all_ups else VOTE_FLAT)

    alignment_by_tf = {}
    for tf in tf_list:
        ups   = sum(1 for s in STRATEGIES if matrix[s][tf] == VOTE_UP)
        downs = sum(1 for s in STRATEGIES if matrix[s][tf] == VOTE_DOWN)
        if ups > downs:
            alignment_by_tf[tf] = "Bullish"
        elif downs > ups:
            alignment_by_tf[tf] = "Bearish"
        else:
            alignment_by_tf[tf] = "Neutral"

    if conflict_score > 0.6:
        warnings.append("High timeframe conflict — signal quality reduced")
    if trend_agreement_score < 40:
        warnings.append("Weak confluence — avoid trading until alignment improves")

    return {
        "matrix":                matrix,
        "regimes":               regimes,
        "tf_scores":             tf_scores,
        "alignment_by_tf":       alignment_by_tf,
        "overall_bias":          overall_bias,
        "strongest_tf":          strongest_tf,
        "trend_agreement_score": trend_agreement_score,
        "conflict_score":        conflict_score,
        "warnings":              warnings,
        "timestamp":             datetime.now(timezone.utc).isoformat(),
    }


# ── Text formatter ───────────────────────────────────────────────────────────────

def format_heatmap_text(result: dict) -> str:
    matrix = result["matrix"]
    regimes = result["regimes"]
    tf_list = list(TIMEFRAMES.keys())

    icon_map = {VOTE_UP: "▲", VOTE_DOWN: "▼", VOTE_FLAT: "→"}

    header = f"{'':12}" + "".join(f"  {tf:>4}" for tf in tf_list)
    lines  = ["XAUUSD — Multi-Timeframe Heatmap\n", header]

    for strat in STRATEGIES:
        row = f"{strat:<12}"
        for tf in tf_list:
            sig  = matrix[strat].get(tf, VOTE_FLAT)
            icon = icon_map.get(sig, "→")
            row += f"  {icon:>4}"
        lines.append(row)

    lines.append("")
    lines.append("Regime:")
    for tf in tf_list:
        lbl = regimes.get(tf, {}).get("label", "Unknown")
        lines.append(f"  {tf:<4}  {lbl}")

    lines.append("")
    lines.append(f"Overall Bias:   {icon_map.get(result['overall_bias'], '→')} {result['overall_bias']}")
    lines.append(f"TF Agreement:   {result['trend_agreement_score']:.0f}%")
    lines.append(f"Strongest TF:   {result['strongest_tf']}")

    if result["warnings"]:
        lines.append("")
        for w in result["warnings"]:
            lines.append(f"Warning: {w}")

    return "\n".join(lines)


# ── Visual heatmap chart ─────────────────────────────────────────────────────────

def generate_heatmap_chart(result: dict) -> io.BytesIO:
    """Generate a dark-theme mobile-optimised heatmap image."""
    matrix   = result["matrix"]
    tf_list  = list(TIMEFRAMES.keys())
    strats   = STRATEGIES

    DARK_BG   = "#0d1117"
    BULL_CLR  = "#00c896"
    BEAR_CLR  = "#ff4560"
    FLAT_CLR  = "#4a5568"
    TEXT_CLR  = "#e2e8f0"
    HEADER_CLR = "#1a202c"

    color_map = {VOTE_UP: BULL_CLR, VOTE_DOWN: BEAR_CLR, VOTE_FLAT: FLAT_CLR}
    icon_map  = {VOTE_UP: "▲", VOTE_DOWN: "▼", VOTE_FLAT: "→"}

    n_rows = len(strats)
    n_cols = len(tf_list)

    fig_w = max(5.5, n_cols * 1.3 + 2.0)
    fig_h = max(3.5, n_rows * 0.7 + 1.8)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_BG)
    ax.axis("off")

    cell_w = 1.0 / (n_cols + 1.5)
    cell_h = 1.0 / (n_rows + 2.0)
    start_x = 0.22
    start_y = 0.82

    for ci, tf in enumerate(tf_list):
        x = start_x + ci * (cell_w + 0.01)
        ax.text(
            x + cell_w / 2, start_y + cell_h * 0.6, tf,
            ha="center", va="center", fontsize=9, fontweight="bold",
            color=TEXT_CLR, transform=ax.transAxes,
        )

    for ri, strat in enumerate(strats):
        y = start_y - (ri + 1) * (cell_h + 0.03)
        ax.text(
            0.02, y + cell_h / 2, strat,
            ha="left", va="center", fontsize=8, color=TEXT_CLR, transform=ax.transAxes,
        )
        for ci, tf in enumerate(tf_list):
            x = start_x + ci * (cell_w + 0.01)
            sig   = matrix[strat].get(tf, VOTE_FLAT)
            clr   = color_map[sig]
            icon  = icon_map[sig]

            rect = mpatches.FancyBboxPatch(
                (x, y), cell_w, cell_h,
                boxstyle="round,pad=0.01",
                facecolor=clr, edgecolor=DARK_BG, linewidth=1.5,
                transform=ax.transAxes, clip_on=False,
            )
            ax.add_patch(rect)
            ax.text(
                x + cell_w / 2, y + cell_h / 2, icon,
                ha="center", va="center", fontsize=10, fontweight="bold",
                color="white", transform=ax.transAxes,
            )

    bottom_y = start_y - (n_rows + 1) * (cell_h + 0.03)
    bias_icon = icon_map.get(result["overall_bias"], "→")
    bias_clr  = color_map.get(result["overall_bias"], FLAT_CLR)
    summary   = f"{bias_icon} {result['overall_bias']}  |  Agreement: {result['trend_agreement_score']:.0f}%"
    ax.text(
        0.5, max(bottom_y - 0.02, 0.04), summary,
        ha="center", va="center", fontsize=9, fontweight="bold",
        color=bias_clr, transform=ax.transAxes,
    )

    ax.set_title(
        "XAUUSD  Multi-Timeframe Heatmap",
        color=TEXT_CLR, fontsize=11, fontweight="bold", pad=8,
    )

    if result["warnings"]:
        warn_text = "  ".join(result["warnings"][:1])
        ax.text(
            0.5, 0.01, f"! {warn_text}",
            ha="center", va="bottom", fontsize=7, color="#f6ad55",
            transform=ax.transAxes,
        )

    plt.tight_layout(pad=0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf
