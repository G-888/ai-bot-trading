"""
charts/debug_charts.py — Debug overlay charts for strategy verification.

Shows every raw detection directly on the chart: swing points, BOS/CHoCH,
order blocks, FVGs, liquidity sweeps, Fibonacci anchors.
"""
import io
import logging
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf

logger = logging.getLogger(__name__)

# ── Colours ──────────────────────────────────────────────────────────────────
DARK_BG      = "#0d1117"
GRID_COLOR   = "#21262d"
BORDER_COLOR = "#30363d"
TEXT_COLOR   = "#f0f6fc"
DIM_TEXT     = "#8b949e"
BULL_COLOR   = "#3fb950"
BEAR_COLOR   = "#f85149"
GOLD_COLOR   = "#f0c040"
ANCHOR_COLOR = "#ff9500"
CHOCH_COLOR  = "#bc8cff"
SWEEP_COLOR  = "#58a6ff"

FIB_COLORS = {
    "0.236": "#58a6ff",
    "0.382": "#3fb950",
    "0.500": "#f0c040",
    "0.618": "#ff7b72",
    "0.786": "#bc8cff",
}

DARK_STYLE = None


def _get_style():
    global DARK_STYLE
    if DARK_STYLE is None:
        DARK_STYLE = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            facecolor=DARK_BG, edgecolor=BORDER_COLOR,
            figcolor=DARK_BG, gridcolor=GRID_COLOR,
            gridstyle="--", gridaxis="both", y_on_right=True,
            rc={"axes.labelcolor": DIM_TEXT, "xtick.color": DIM_TEXT,
                "ytick.color": DIM_TEXT, "font.size": 7},
        )
    return DARK_STYLE


def _prep(df: pd.DataFrame, tail: int = 60) -> pd.DataFrame:
    df = df.tail(tail).copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo is not None else df.index
    return df


def _ts_map(df: pd.DataFrame) -> dict:
    """Map timestamp → integer bar position (0-based)."""
    return {ts: i for i, ts in enumerate(df.index)}


def _scatter_series(df: pd.DataFrame, bar_pos_price: list[tuple]) -> pd.Series:
    """Return a Series aligned to df with values at given (bar_pos, price) pairs."""
    s = pd.Series(np.nan, index=df.index)
    for pos, price in bar_pos_price:
        if pos is not None and 0 <= pos < len(df):
            s.iloc[pos] = price
    return s


def _export(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


# ═══════════════════════════════════════════════════════════════════════════════
# DEBUG FIBONACCI CHART
# ═══════════════════════════════════════════════════════════════════════════════

def generate_debug_fib_chart(df: pd.DataFrame, fib_result: dict, lookback: int = 4) -> io.BytesIO:
    """
    Candlestick with ALL detected swing points and Fibonacci anchor overlays.
    Green ▲ = all swing highs  |  Red ▼ = all swing lows
    Gold ★ = anchor (used for Fib calc)  |  Dashed vertical = anchors
    Horizontal lines = all Fib levels colour-coded
    """
    from market.indicators import swing_highs, swing_lows

    df = _prep(df, 60)
    ts_idx = _ts_map(df)
    n = len(df)

    # ── All swing highs / lows on the tail df ─────────────────────────────────
    sh_mask = swing_highs(df["High"], lookback)
    sl_mask = swing_lows(df["Low"], lookback)

    sh_pairs = [(ts_idx.get(ts), round(float(p), 2)) for ts, p in df["High"][sh_mask].items()]
    sl_pairs = [(ts_idx.get(ts), round(float(p), 2)) for ts, p in df["Low"][sl_mask].items()]

    # ── Build addplot scatter series ───────────────────────────────────────────
    sh_series = _scatter_series(df, [(pos, price * 1.0008) for pos, price in sh_pairs])
    sl_series = _scatter_series(df, [(pos, price * 0.9992) for pos, price in sl_pairs])

    add_plots = []
    if sh_series.notna().any():
        add_plots.append(mpf.make_addplot(
            sh_series, type="scatter", marker="^",
            color=BULL_COLOR, markersize=80, panel=0,
        ))
    if sl_series.notna().any():
        add_plots.append(mpf.make_addplot(
            sl_series, type="scatter", marker="v",
            color=BEAR_COLOR, markersize=80, panel=0,
        ))

    # ── Price line ─────────────────────────────────────────────────────────────
    price = fib_result.get("price", float(df["Close"].iloc[-1]))
    add_plots.append(mpf.make_addplot(
        pd.Series([price] * n, index=df.index),
        color=GOLD_COLOR, width=1.2, linestyle=":", panel=0,
    ))

    fig, axes = mpf.plot(
        df, type="candle", style=_get_style(),
        volume=False, addplot=add_plots,
        figsize=(11, 7), title="", tight_layout=True,
        returnfig=True, warn_too_much_data=9999,
    )
    ax = axes[0]
    ax.set_title("  XAUUSD  •  DEBUG Fibonacci  (1H, 60 bars)",
                 color=TEXT_COLOR, fontsize=11, fontweight="bold", loc="left", pad=10)

    # ── Fibonacci horizontal lines ─────────────────────────────────────────────
    levels = fib_result.get("levels", {})
    nearest_price = fib_result.get("nearest_price")
    legend_patches = []

    for name, lp in sorted(levels.items(), key=lambda x: x[1], reverse=True):
        is_nearest = nearest_price is not None and abs(lp - nearest_price) < 0.01
        color = FIB_COLORS.get(name, DIM_TEXT)
        lw = 2.0 if is_nearest else 0.9
        ls = "-" if is_nearest else "--"
        alpha = 1.0 if is_nearest else 0.7
        ax.axhline(y=lp, color=color, linewidth=lw, linestyle=ls, alpha=alpha)
        suffix = " ◄ nearest" if is_nearest else ""
        ax.text(n - 0.5, lp, f" {name} {lp}{suffix}",
                color=color, fontsize=6.5, va="center", ha="left", alpha=alpha,
                clip_on=False)
        legend_patches.append(mpatches.Patch(color=color, label=f"{name}: {lp}"))

    # ── Anchor candles (vertical lines + star markers) ─────────────────────────
    swing_high = fib_result.get("swing_high")
    swing_low = fib_result.get("swing_low")

    for anchor_price, label in [(swing_high, "SH ★"), (swing_low, "SL ★")]:
        if anchor_price is None:
            continue
        col = BULL_COLOR if label.startswith("SH") else BEAR_COLOR
        # find bar closest to anchor_price in df
        close_vals = df["High"] if label.startswith("SH") else df["Low"]
        closest_idx = int((close_vals - anchor_price).abs().argmin())
        ax.axvline(x=closest_idx, color=ANCHOR_COLOR, linewidth=1.5,
                   linestyle="--", alpha=0.8, label=label)
        ax.text(closest_idx, anchor_price, f"\n {label} {anchor_price}",
                color=ANCHOR_COLOR, fontsize=7, fontweight="bold",
                va="bottom" if label.startswith("SH") else "top", ha="center")

    # ── Info box ───────────────────────────────────────────────────────────────
    direction_arrow = "▼" if "down" in fib_result.get("direction", "") else "▲"
    info = (
        f"Direction: {direction_arrow} {fib_result.get('bias', '')}\n"
        f"Swing High: {swing_high}  Swing Low: {swing_low}\n"
        f"Nearest: {fib_result.get('nearest_level', 'N/A')} at {fib_result.get('nearest_price', 'N/A')}\n"
        f"Confluence: {fib_result.get('confluence_score', 0):.0f}%  RSI: {fib_result.get('rsi', 0)}"
    )
    ax.text(0.01, 0.01, info, transform=ax.transAxes,
            color=TEXT_COLOR, fontsize=7, va="bottom", ha="left",
            bbox=dict(facecolor=DARK_BG, edgecolor=BORDER_COLOR, alpha=0.85, pad=4))

    # ── Count legend ───────────────────────────────────────────────────────────
    summary_patches = [
        mpatches.Patch(color=BULL_COLOR, label=f"Swing Highs: {len(sh_pairs)}"),
        mpatches.Patch(color=BEAR_COLOR, label=f"Swing Lows: {len(sl_pairs)}"),
        mpatches.Patch(color=ANCHOR_COLOR, label="Anchor candles"),
        mpatches.Patch(color=GOLD_COLOR, label=f"Price: {price}"),
    ]
    ax.legend(handles=summary_patches, loc="upper right", framealpha=0.3,
              facecolor=DARK_BG, edgecolor=BORDER_COLOR, labelcolor=TEXT_COLOR, fontsize=7)

    fig.patch.set_facecolor(DARK_BG)
    return _export(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# DEBUG SMC CHART
# ═══════════════════════════════════════════════════════════════════════════════

def generate_debug_smc_chart(df: pd.DataFrame, smc_result: dict, lookback: int = 3) -> io.BytesIO:
    """
    Candlestick with all SMC detections overlaid:
    ▲/▼ = swing points  |  solid vertical = BOS  |  dashed vertical = CHoCH
    Shaded zones = order blocks  |  lighter zones = FVGs
    ● = liquidity sweep candles
    """
    from market.indicators import swing_highs, swing_lows

    df = _prep(df, 60)
    ts_idx = _ts_map(df)
    n = len(df)

    sh_mask = swing_highs(df["High"], lookback)
    sl_mask = swing_lows(df["Low"], lookback)

    sh_pairs = [(ts_idx.get(ts), round(float(p), 2)) for ts, p in df["High"][sh_mask].items()]
    sl_pairs = [(ts_idx.get(ts), round(float(p), 2)) for ts, p in df["Low"][sl_mask].items()]

    sh_series = _scatter_series(df, [(pos, price * 1.0008) for pos, price in sh_pairs])
    sl_series = _scatter_series(df, [(pos, price * 0.9992) for pos, price in sl_pairs])

    # Sweep markers at extremes
    sweeps = smc_result.get("sweeps", [])
    sweep_points = []
    for sw in sweeps:
        bar = sw.get("bar_idx")
        if bar is not None and 0 <= bar < n:
            if "Bearish" in sw["type"]:
                sweep_points.append((bar, float(df["High"].iloc[bar]) * 1.001))
            else:
                sweep_points.append((bar, float(df["Low"].iloc[bar]) * 0.999))
    sweep_series = _scatter_series(df, sweep_points)

    price = smc_result.get("price", float(df["Close"].iloc[-1]))
    price_series = pd.Series([price] * n, index=df.index)

    add_plots = []
    if sh_series.notna().any():
        add_plots.append(mpf.make_addplot(sh_series, type="scatter", marker="^",
                                          color=BULL_COLOR, markersize=70, panel=0))
    if sl_series.notna().any():
        add_plots.append(mpf.make_addplot(sl_series, type="scatter", marker="v",
                                          color=BEAR_COLOR, markersize=70, panel=0))
    if sweep_series.notna().any():
        add_plots.append(mpf.make_addplot(sweep_series, type="scatter", marker="o",
                                          color=SWEEP_COLOR, markersize=100, panel=0))
    add_plots.append(mpf.make_addplot(price_series, color=GOLD_COLOR,
                                      width=1.2, linestyle=":", panel=0))

    fig, axes = mpf.plot(
        df, type="candle", style=_get_style(),
        volume=False, addplot=add_plots,
        figsize=(11, 7), title="", tight_layout=True,
        returnfig=True, warn_too_much_data=9999,
    )
    ax = axes[0]
    ax.set_title("  XAUUSD  •  DEBUG Smart Money Concepts  (1H, 60 bars)",
                 color=TEXT_COLOR, fontsize=11, fontweight="bold", loc="left", pad=10)

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()

    # ── Order blocks ───────────────────────────────────────────────────────────
    for ob in smc_result.get("order_blocks", []):
        bar = ob.get("bar_idx", 0)
        color = "#3fb95033" if "Bullish" in ob["type"] else "#f8514933"
        edge  = BULL_COLOR  if "Bullish" in ob["type"] else BEAR_COLOR
        x_start = max(0, bar - 0.5)
        ax.axhspan(ob["bottom"], ob["top"], xmin=x_start / n, xmax=1.0,
                   facecolor=color, edgecolor=edge, linewidth=0.6, alpha=0.7)
        ax.text(x_start, ob["mid"], f" {ob['type'][:3]} OB",
                color=edge, fontsize=6, va="center", fontweight="bold")

    # ── Fair value gaps ────────────────────────────────────────────────────────
    for fvg in smc_result.get("fvg_list", []):
        bar = fvg.get("bar_idx", 0)
        color = "#3fb95018" if "Bullish" in fvg["type"] else "#f8514918"
        ax.axhspan(fvg["bottom"], fvg["top"], facecolor=color, edgecolor="none", alpha=0.8)
        ax.text(n * 0.55, fvg["mid"], f" FVG",
                color=DIM_TEXT, fontsize=6, va="center")

    # ── BOS vertical lines ─────────────────────────────────────────────────────
    for b in smc_result.get("bos_list", []):
        bar = b.get("bar", 0)
        if 0 <= bar < n:
            color = BULL_COLOR if b["direction"] == "Bullish" else BEAR_COLOR
            ax.axvline(x=bar, color=color, linewidth=1.5, linestyle="-", alpha=0.85)
            ax.text(bar, ylim[1] * 0.999, f" BOS {b['direction'][:4]}",
                    color=color, fontsize=6.5, va="top", fontweight="bold", rotation=90)

    # ── CHoCH vertical lines ───────────────────────────────────────────────────
    for c in smc_result.get("choch_list", []):
        bar = c.get("bar", 0)
        if 0 <= bar < n:
            ax.axvline(x=bar, color=CHOCH_COLOR, linewidth=1.5, linestyle="--", alpha=0.9)
            ax.text(bar, ylim[0] * 1.001, f" CHoCH",
                    color=CHOCH_COLOR, fontsize=6.5, va="bottom", fontweight="bold", rotation=90)

    # ── Sweep labels ───────────────────────────────────────────────────────────
    for sw in sweeps:
        bar = sw.get("bar_idx")
        if bar is not None and 0 <= bar < n:
            label = "Sw↑" if "Bullish" in sw["type"] else "Sw↓"
            ypos = float(df["Low"].iloc[bar]) if "Bullish" in sw["type"] else float(df["High"].iloc[bar])
            ax.text(bar, ypos, f"\n{label}", color=SWEEP_COLOR, fontsize=6.5,
                    ha="center", va="top" if "Bearish" in sw["type"] else "bottom")

    # ── Info box ───────────────────────────────────────────────────────────────
    bos_summary = ", ".join(f"{b['direction']} @{b['level']}" for b in smc_result.get("bos_list", [])) or "None"
    ch_summary  = ", ".join(f"{c['direction']} @{c['level']}" for c in smc_result.get("choch_list", [])) or "None"
    info = (
        f"Structure: {smc_result.get('structure_bias', 'N/A')}\n"
        f"Bias: {smc_result.get('overall_bias', 'N/A')}\n"
        f"BOS: {bos_summary}\n"
        f"CHoCH: {ch_summary}\n"
        f"Zone: {smc_result.get('premium_discount', 'N/A')}"
    )
    ax.text(0.01, 0.01, info, transform=ax.transAxes,
            color=TEXT_COLOR, fontsize=6.5, va="bottom",
            bbox=dict(facecolor=DARK_BG, edgecolor=BORDER_COLOR, alpha=0.85, pad=4))

    legend_patches = [
        mpatches.Patch(color=BULL_COLOR,  label=f"Swing Highs ({len(sh_pairs)})"),
        mpatches.Patch(color=BEAR_COLOR,  label=f"Swing Lows ({len(sl_pairs)})"),
        mpatches.Patch(color=BULL_COLOR,  label=f"Bullish BOS ({smc_result.get('bos_count', 0)})"),
        mpatches.Patch(color=CHOCH_COLOR, label=f"CHoCH ({smc_result.get('choch_count', 0)})"),
        mpatches.Patch(color=SWEEP_COLOR, label=f"Sweeps ({smc_result.get('sweep_count', 0)})"),
        mpatches.Patch(color="#3fb950aa", label=f"OBs ({len(smc_result.get('order_blocks', []))})"),
        mpatches.Patch(color="#f0c04066", label=f"FVGs ({len(smc_result.get('fvg_list', []))})"),
    ]
    ax.legend(handles=legend_patches, loc="upper right", framealpha=0.3, ncol=2,
              facecolor=DARK_BG, edgecolor=BORDER_COLOR, labelcolor=TEXT_COLOR, fontsize=6.5)
    fig.patch.set_facecolor(DARK_BG)
    return _export(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# DEBUG CONFLUENCE CHART (horizontal bar chart, no candlestick)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_debug_confluence_chart(confluence_result: dict) -> io.BytesIO:
    """
    Pure matplotlib horizontal bar chart showing each confluence factor's score.
    Color-coded: green ≥70%  |  gold 40-69%  |  red <40%
    """
    bd = confluence_result.get("breakdown", {})
    total = confluence_result.get("total", 0)
    direction = confluence_result.get("direction", "N/A")
    strength = confluence_result.get("signal_strength", "N/A")

    # factor maximums (must match signals/confluence.py)
    maxima = {
        "TF Alignment": 25,
        "SMC": 20,
        "Fibonacci": 15,
        "RSI": 15,
        "Session": 15,
        "Volatility": 10,
    }

    factors = list(bd.keys())
    scores = [bd[f][0] for f in factors]
    notes  = [bd[f][1] for f in factors]
    maxes  = [maxima.get(f, 100) for f in factors]
    pcts   = [s / m * 100 for s, m in zip(scores, maxes)]

    bar_colors = []
    for pct in pcts:
        if pct >= 70:
            bar_colors.append(BULL_COLOR)
        elif pct >= 40:
            bar_colors.append(GOLD_COLOR)
        else:
            bar_colors.append(BEAR_COLOR)

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_BG)

    y_pos = range(len(factors))
    bars = ax.barh(
        list(y_pos), scores,
        color=bar_colors, height=0.55, alpha=0.85,
        edgecolor=BORDER_COLOR, linewidth=0.5,
    )
    # max markers
    ax.barh(
        list(y_pos), maxes,
        color="none", height=0.55,
        edgecolor=DIM_TEXT, linewidth=0.8, linestyle="--",
    )

    for i, (bar, score, maxv, pct, note) in enumerate(zip(bars, scores, maxes, pcts, notes)):
        ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2,
                f"{score:.1f}/{maxv}  ({pct:.0f}%)   {note}",
                va="center", ha="left", color=TEXT_COLOR, fontsize=8)

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(factors, color=TEXT_COLOR, fontsize=9)
    ax.set_xlabel("Score", color=DIM_TEXT, fontsize=8)
    ax.set_xlim(0, max(maxes) * 1.5)
    ax.tick_params(colors=DIM_TEXT, which="both")
    ax.spines[:].set_edgecolor(BORDER_COLOR)
    ax.grid(axis="x", color=GRID_COLOR, linestyle="--", linewidth=0.5)

    total_bar_color = BULL_COLOR if total >= 70 else (GOLD_COLOR if total >= 45 else BEAR_COLOR)
    signal_dir = "▲ BUY" if direction == "BUY" else "▼ SELL"

    ax.set_title(
        f"  XAUUSD  •  DEBUG Confluence Score\n"
        f"  Total: {total:.0f}/100   Signal: {signal_dir}   Strength: {strength}",
        color=TEXT_COLOR, fontsize=10, fontweight="bold", loc="left", pad=12,
    )

    total_pct = total / 100
    ax.axvspan(0, 0, 0, 1)

    total_line_x = total / max(maxes) * max(maxes)
    ax.axvline(x=0, color="none")

    score_text = f"TOTAL  {total:.0f} / 100"
    fig.text(0.98, 0.02, score_text, ha="right", va="bottom",
             color=total_bar_color, fontsize=13, fontweight="bold")

    fig.tight_layout(pad=1.5)
    return _export(fig)
