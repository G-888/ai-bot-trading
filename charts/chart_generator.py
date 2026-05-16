"""
charts/chart_generator.py — Advanced dark-theme chart generation.

Supports: base candlestick, Fibonacci overlays, SMC overlays, EMA overlays,
session markers. Optimised for Telegram mobile viewing.
"""
import io
import logging
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ── Theme ─────────────────────────────────────────────────────────────────────
DARK_BG = "#0d1117"
GRID_COLOR = "#21262d"
BORDER_COLOR = "#30363d"
TEXT_COLOR = "#f0f6fc"
DIM_TEXT = "#8b949e"
BULL_COLOR = "#3fb950"
BEAR_COLOR = "#f85149"
GOLD_COLOR = "#f0c040"
FIB_COLORS = {
    "0.236": "#58a6ff",
    "0.382": "#3fb950",
    "0.500": "#f0c040",
    "0.618": "#ff7b72",
    "0.786": "#bc8cff",
}
FIB_DEFAULT = "#8b949e"
SMC_OB_BULL = "#3fb95033"
SMC_OB_BEAR = "#f8514933"
SMC_FVG_BULL = "#3fb95022"
SMC_FVG_BEAR = "#f8514922"
EMA_COLORS = {50: "#f0c040", 200: "#58a6ff"}


def _dark_style():
    return mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        facecolor=DARK_BG,
        edgecolor=BORDER_COLOR,
        figcolor=DARK_BG,
        gridcolor=GRID_COLOR,
        gridstyle="--",
        gridaxis="both",
        y_on_right=True,
        rc={
            "axes.labelcolor": DIM_TEXT,
            "xtick.color": DIM_TEXT,
            "ytick.color": DIM_TEXT,
            "font.size": 8,
        },
    )


def _prep_df(df: pd.DataFrame, tail: int = 48) -> pd.DataFrame:
    df = df.tail(tail).copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo is not None else df.index
    return df


def generate_base_chart(
    df: pd.DataFrame,
    price: float,
    support: float,
    resistance: float,
    title: str = "XAUUSD  •  48h",
    tail: int = 48,
    add_emas: bool = True,
) -> io.BytesIO:
    """Generate standard dark candlestick chart."""
    df = _prep_df(df, tail)

    add_plots = [
        mpf.make_addplot([price] * len(df), color=GOLD_COLOR, width=1.2, linestyle="--"),
        mpf.make_addplot([support] * len(df), color=BULL_COLOR, width=1.5),
        mpf.make_addplot([resistance] * len(df), color=BEAR_COLOR, width=1.5),
    ]

    if add_emas and len(df) >= 20:
        from market.indicators import ema as calc_ema
        for period, color in EMA_COLORS.items():
            if len(df) >= period:
                e = calc_ema(df["Close"], period).reindex(df.index)
                add_plots.append(mpf.make_addplot(e, color=color, width=1.0))

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=_dark_style(),
        volume=True,
        addplot=add_plots,
        figsize=(10, 6),
        title="",
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=9999,
        volume_panel=1,
        panel_ratios=(3, 1),
    )

    ax = axes[0]
    ax.set_title(f"  {title}", color=TEXT_COLOR, fontsize=12, fontweight="bold", loc="left", pad=10)

    legend_patches = [
        mpatches.Patch(color=GOLD_COLOR, label=f"Price: {price}"),
        mpatches.Patch(color=BULL_COLOR, label=f"Support: {support}"),
        mpatches.Patch(color=BEAR_COLOR, label=f"Resistance: {resistance}"),
    ]
    if add_emas and len(df) >= 50:
        legend_patches.append(mpatches.Patch(color=EMA_COLORS[50], label="EMA 50"))
    if add_emas and len(df) >= 200:
        legend_patches.append(mpatches.Patch(color=EMA_COLORS[200], label="EMA 200"))

    ax.legend(handles=legend_patches, loc="upper left", framealpha=0.3,
              facecolor=DARK_BG, edgecolor=BORDER_COLOR, labelcolor=TEXT_COLOR, fontsize=7)
    fig.patch.set_facecolor(DARK_BG)

    return _export(fig)


def generate_fib_chart(
    df: pd.DataFrame,
    fib_result: dict,
    title: str = "XAUUSD  •  Fibonacci",
) -> io.BytesIO:
    """Generate candlestick chart with Fibonacci overlay."""
    df = _prep_df(df, 60)

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=_dark_style(),
        volume=False,
        figsize=(10, 7),
        title="",
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=9999,
    )

    ax = axes[0]
    ax.set_title(f"  {title}", color=TEXT_COLOR, fontsize=12, fontweight="bold", loc="left", pad=10)

    levels = fib_result.get("levels", {})
    price = fib_result.get("price", 0)
    swing_high = fib_result.get("swing_high", 0)
    swing_low = fib_result.get("swing_low", 0)

    legend_patches = []
    for name, level_price in sorted(levels.items(), key=lambda x: x[1], reverse=True):
        color = FIB_COLORS.get(name, FIB_DEFAULT)
        linestyle = "--" if name not in ("0.0 (Swing High)", "1.0 (Swing Low)", "0.0 (Swing Low)", "1.0 (Swing High)") else "-"
        ax.axhline(y=level_price, color=color, linewidth=1.0, linestyle=linestyle, alpha=0.8)
        ax.text(ax.get_xlim()[0], level_price, f" {name} {level_price}", color=color,
                fontsize=7, va="center", alpha=0.9)
        legend_patches.append(mpatches.Patch(color=color, label=f"{name}: {level_price}"))

    ax.axhline(y=price, color=GOLD_COLOR, linewidth=1.5, linestyle=":", alpha=0.9)

    nearest = fib_result.get("nearest_price")
    if nearest:
        ax.axhspan(nearest * 0.999, nearest * 1.001, alpha=0.15, color=GOLD_COLOR, label="Price zone")

    ax.legend(handles=legend_patches[:8], loc="upper left", framealpha=0.3,
              facecolor=DARK_BG, edgecolor=BORDER_COLOR, labelcolor=TEXT_COLOR, fontsize=6, ncol=2)
    fig.patch.set_facecolor(DARK_BG)
    return _export(fig)


def generate_smc_chart(
    df: pd.DataFrame,
    smc_result: dict,
    title: str = "XAUUSD  •  Smart Money Concepts",
) -> io.BytesIO:
    """Generate candlestick chart with SMC overlays (OBs, FVGs)."""
    df = _prep_df(df, 60)

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=_dark_style(),
        volume=False,
        figsize=(10, 7),
        title="",
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=9999,
    )

    ax = axes[0]
    ax.set_title(f"  {title}", color=TEXT_COLOR, fontsize=12, fontweight="bold", loc="left", pad=10)

    n = len(df)
    xlim = ax.get_xlim()

    for ob in smc_result.get("order_blocks", [])[-5:]:
        color = SMC_OB_BULL if "Bullish" in ob["type"] else SMC_OB_BEAR
        edge = BULL_COLOR if "Bullish" in ob["type"] else BEAR_COLOR
        bar_idx = ob.get("bar_idx", n - 1)
        x_start = max(0, bar_idx - 1)
        ax.axhspan(ob["bottom"], ob["top"], xmin=x_start / n, xmax=1.0,
                   facecolor=color, edgecolor=edge, linewidth=0.5, alpha=0.6)
        ax.text(xlim[0], ob["mid"], f" {ob['type']}", color=edge, fontsize=6, va="center", alpha=0.9)

    for fvg in smc_result.get("fvg_list", [])[-5:]:
        color = SMC_FVG_BULL if "Bullish" in fvg["type"] else SMC_FVG_BEAR
        ax.axhspan(fvg["bottom"], fvg["top"], facecolor=color, edgecolor="none", alpha=0.5)
        ax.text(xlim[1] * 0.5, fvg["mid"], f" FVG {fvg['type'][:4]}", color=DIM_TEXT,
                fontsize=6, va="center", alpha=0.8)

    price = smc_result.get("price", 0)
    ax.axhline(y=price, color=GOLD_COLOR, linewidth=1.5, linestyle=":", alpha=0.9)

    legend_patches = [
        mpatches.Patch(color=BULL_COLOR, label="Bullish OB"),
        mpatches.Patch(color=BEAR_COLOR, label="Bearish OB"),
        mpatches.Patch(color="#3fb95055", label="Bullish FVG"),
        mpatches.Patch(color="#f8514955", label="Bearish FVG"),
        mpatches.Patch(color=GOLD_COLOR, label=f"Price: {price}"),
    ]
    ax.legend(handles=legend_patches, loc="upper left", framealpha=0.3,
              facecolor=DARK_BG, edgecolor=BORDER_COLOR, labelcolor=TEXT_COLOR, fontsize=7)
    fig.patch.set_facecolor(DARK_BG)
    return _export(fig)


def _export(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf
