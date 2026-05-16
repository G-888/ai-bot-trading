"""
backtesting/reports.py — Chart generation for backtest results.

Generates equity curve and drawdown charts optimized for mobile Telegram viewing.
"""
import io
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)

DARK_BG   = "#0d1117"
BULL_CLR  = "#00c896"
BEAR_CLR  = "#ff4560"
FLAT_CLR  = "#4a5568"
GRID_CLR  = "#1e2530"
TEXT_CLR  = "#e2e8f0"
ACCENT    = "#63b3ed"
WARN_CLR  = "#f6ad55"


def generate_backtest_charts(metrics: dict, meta: dict) -> io.BytesIO:
    """
    Generate combined equity curve + drawdown chart.
    Returns PNG buffer suitable for Telegram send_photo.
    """
    equity = metrics.get("equity_curve", [0.0])
    if len(equity) < 2:
        equity = [0.0, 0.0]

    drawdown = _build_drawdown(equity)
    trades   = metrics.get("total_trades", 0)
    strategy = meta.get("strategy", "").upper()
    tf       = meta.get("timeframe", "")
    lookback = meta.get("lookback", "")

    fig = plt.figure(figsize=(7, 5.5), facecolor=DARK_BG)
    gs  = gridspec.GridSpec(3, 1, hspace=0.08, height_ratios=[2.5, 0.05, 1.2])

    ax_eq = fig.add_subplot(gs[0])
    ax_dd = fig.add_subplot(gs[2])

    _style_ax(ax_eq)
    _style_ax(ax_dd)

    x = list(range(len(equity)))

    ax_eq.plot(x, equity, color=ACCENT, linewidth=1.6, zorder=3)
    ax_eq.fill_between(x, equity, 0, where=[v >= 0 for v in equity],
                       alpha=0.15, color=BULL_CLR, zorder=2)
    ax_eq.fill_between(x, equity, 0, where=[v < 0 for v in equity],
                       alpha=0.15, color=BEAR_CLR, zorder=2)
    ax_eq.axhline(0, color=FLAT_CLR, linewidth=0.8, linestyle="--", zorder=1)

    final_pnl = equity[-1]
    pnl_color = BULL_CLR if final_pnl >= 0 else BEAR_CLR
    ax_eq.text(
        0.02, 0.93,
        f"PnL: {final_pnl:+.2f} pts",
        transform=ax_eq.transAxes, color=pnl_color,
        fontsize=9, fontweight="bold", va="top",
    )
    ax_eq.text(
        0.02, 0.80,
        f"{trades} trades",
        transform=ax_eq.transAxes, color=TEXT_CLR, fontsize=7.5, va="top",
    )

    ax_eq.set_title(
        f"XAUUSD Backtest  |  {strategy}  |  {tf}  |  {lookback}",
        color=TEXT_CLR, fontsize=9.5, fontweight="bold", pad=6,
    )
    ax_eq.set_ylabel("PnL (pts)", color=TEXT_CLR, fontsize=7.5)
    ax_eq.tick_params(labelbottom=False)

    dd_color = [BEAR_CLR if d < 0 else FLAT_CLR for d in drawdown]
    ax_dd.fill_between(range(len(drawdown)), drawdown, 0,
                       alpha=0.65, color=BEAR_CLR, zorder=2)
    ax_dd.plot(range(len(drawdown)), drawdown, color=BEAR_CLR, linewidth=0.9, zorder=3)
    ax_dd.axhline(0, color=FLAT_CLR, linewidth=0.6, linestyle="--")
    ax_dd.set_ylabel("Drawdown", color=TEXT_CLR, fontsize=7.5)
    ax_dd.set_xlabel("Trade #", color=TEXT_CLR, fontsize=7.5)

    max_dd = metrics.get("max_drawdown", 0.0)
    ax_dd.text(
        0.02, 0.15,
        f"Max DD: {max_dd:.2f} pts",
        transform=ax_dd.transAxes, color=WARN_CLR, fontsize=7.5, va="bottom",
    )

    wr  = metrics.get("win_rate", 0)
    pf  = metrics.get("profit_factor", 0)
    sh  = metrics.get("sharpe_like", 0)
    exp = metrics.get("expectancy", 0)
    pf_str = f"{pf:.2f}" if pf < 100 else "∞"

    summary = f"WR {wr:.0f}%   PF {pf_str}   Exp {exp:+.2f}   Sharpe {sh:.2f}"
    fig.text(
        0.5, 0.01, summary,
        ha="center", va="bottom", fontsize=7.5,
        color=TEXT_CLR, fontweight="bold",
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0)
    plt.close(fig)
    return buf


def _build_drawdown(equity: list) -> list:
    peak = equity[0]
    dd   = []
    for val in equity:
        if val > peak:
            peak = val
        dd.append(val - peak)
    return dd


def _style_ax(ax) -> None:
    ax.set_facecolor(DARK_BG)
    ax.tick_params(colors=TEXT_CLR, labelsize=6.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID_CLR)
    ax.spines["bottom"].set_color(GRID_CLR)
    ax.yaxis.label.set_color(TEXT_CLR)
    ax.xaxis.label.set_color(TEXT_CLR)
    ax.grid(axis="y", color=GRID_CLR, linewidth=0.5, alpha=0.6)
