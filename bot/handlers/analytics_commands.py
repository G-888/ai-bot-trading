"""
bot/handlers/analytics_commands.py — Analytics & research commands.

Handles: /performance, /leaderboard, /diagnostics, /compare, /optimize
Python computes everything. AI explains only where invoked explicitly.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.menus import back_to_menu

logger = logging.getLogger(__name__)

VALID_STRATEGIES = {"fib", "fibonacci", "smc", "confluence"}


# ── /performance ─────────────────────────────────────────────────────────────────

async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pull real backtest history and produce an institutional performance report."""
    status = await update.message.reply_text("Compiling performance report from backtest history…")
    try:
        from analytics.performance import (
            get_performance_stats,
            format_performance_report,
            generate_performance_charts,
            generate_monthly_heatmap,
        )
        import storage.database as db

        stats = get_performance_stats()

        if not stats:
            await status.edit_text(
                "No backtest data found.\n\n"
                "Run backtests first to build history:\n"
                "/backtest fib 1H 30d\n"
                "/backtest smc 1H 30d\n"
                "/backtest confluence 1H 30d",
                reply_markup=back_to_menu(),
            )
            return

        for strat_key, s in stats.items():
            db.save_performance_snapshot(
                strategy=strat_key,
                win_rate=s["win_rate"],
                profit_factor=s["profit_factor"],
                expectancy=s["expectancy"],
                total_trades=s["total_trades"],
                vol_adj_score=s["vol_adj_score"],
            )

        report_text  = format_performance_report(stats)
        perf_chart   = generate_performance_charts(stats)
        monthly_chart = generate_monthly_heatmap(stats)

        await status.delete()

        await update.message.reply_photo(
            photo=perf_chart,
            caption="Strategy Performance Dashboard",
            reply_markup=back_to_menu(),
        )

        await update.message.reply_photo(
            photo=monthly_chart,
            caption="Monthly PnL — Best Strategy",
        )

        chunk = 4000
        for i in range(0, len(report_text), chunk):
            await update.message.reply_text(
                report_text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(report_text) else None,
            )

    except Exception as e:
        logger.error("cmd_performance error: %s", e, exc_info=True)
        await status.edit_text(f"Performance report error: {e}")


# ── /leaderboard ─────────────────────────────────────────────────────────────────

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rank all strategies by composite institutional score."""
    status = await update.message.reply_text("Building strategy leaderboard…")
    try:
        from analytics.performance import get_performance_stats
        from analytics.leaderboard import build_leaderboard, format_leaderboard_text, generate_leaderboard_chart

        stats  = get_performance_stats()
        ranked = build_leaderboard(stats)
        text   = format_leaderboard_text(ranked)
        chart  = generate_leaderboard_chart(ranked)

        await status.delete()
        await update.message.reply_photo(
            photo=chart,
            caption="Strategy Leaderboard",
            reply_markup=back_to_menu(),
        )

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_leaderboard error: %s", e, exc_info=True)
        await status.edit_text(f"Leaderboard error: {e}")


# ── /diagnostics ─────────────────────────────────────────────────────────────────

async def cmd_diagnostics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run health diagnostics on all strategy backtests."""
    status = await update.message.reply_text("Running strategy diagnostics…")
    try:
        from analytics.performance import get_performance_stats
        from analytics.diagnostics import run_diagnostics, format_diagnostics_text

        stats      = get_performance_stats()
        all_issues = run_diagnostics(stats)
        text       = format_diagnostics_text(all_issues, stats)

        await status.delete()

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_diagnostics error: %s", e, exc_info=True)
        await status.edit_text(f"Diagnostics error: {e}")


# ── /compare ─────────────────────────────────────────────────────────────────────

async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Side-by-side strategy comparison.
    Usage: /compare fib smc
    """
    args = context.args or []

    if len(args) < 2:
        await update.message.reply_text(
            "Compare two strategies side-by-side.\n\n"
            "Usage: /compare <strategy1> <strategy2>\n\n"
            "Examples:\n"
            "/compare fib smc\n"
            "/compare smc confluence\n"
            "/compare fib confluence\n\n"
            "Valid: fib, smc, confluence",
            reply_markup=back_to_menu(),
        )
        return

    s1 = args[0].lower().replace("fibonacci", "fib")
    s2 = args[1].lower().replace("fibonacci", "fib")

    for s in (s1, s2):
        if s not in VALID_STRATEGIES:
            await update.message.reply_text(
                f"Unknown strategy '{s}'.\nValid: fib, smc, confluence",
                reply_markup=back_to_menu(),
            )
            return

    status = await update.message.reply_text(
        f"Comparing {s1.upper()} vs {s2.upper()}…"
    )
    try:
        from analytics.performance import get_performance_stats, generate_performance_charts

        stats = get_performance_stats()
        subset = {k: v for k, v in stats.items() if k in (s1, s2)}

        if len(subset) < 2:
            missing = [x for x in (s1, s2) if x not in stats]
            await status.edit_text(
                f"No backtest data for: {', '.join(missing).upper()}\n\n"
                f"Run first:\n"
                + "\n".join(f"/backtest {m} 1H 30d" for m in missing),
                reply_markup=back_to_menu(),
            )
            return

        text  = _format_comparison(subset, s1, s2, stats)
        chart = generate_performance_charts(subset)

        await status.delete()
        await update.message.reply_photo(
            photo=chart,
            caption=f"Comparison: {s1.upper()} vs {s2.upper()}",
            reply_markup=back_to_menu(),
        )

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_compare error: %s", e, exc_info=True)
        await status.edit_text(f"Comparison error: {e}")


def _format_comparison(subset: dict, s1: str, s2: str, all_stats: dict) -> str:
    """Generate a side-by-side comparison table."""
    a = subset.get(s1, {})
    b = subset.get(s2, {})

    def _pf(v):
        return f"{v:.2f}" if v < 100 else "∞"

    def _winner(va, vb, higher_is_better=True):
        if va == vb:
            return "="
        if higher_is_better:
            return "◀" if va > vb else "▶"
        return "◀" if va < vb else "▶"

    label_a = a.get("label", s1.upper())
    label_b = b.get("label", s2.upper())

    def row(metric, va, vb, fmt="{:.2f}", higher_better=True):
        try:
            fa = fmt.format(va) if isinstance(va, (int, float)) else str(va)
            fb = fmt.format(vb) if isinstance(vb, (int, float)) else str(vb)
        except Exception:
            fa, fb = str(va), str(vb)
        w = _winner(va, vb, higher_better)
        return f"  {metric:<18} {fa:>8}  {w}  {fb:<8}"

    lines = [
        f"Strategy Comparison",
        f"{label_a}  vs  {label_b}",
        "=" * 40,
        f"  {'Metric':<18} {'':>8}     {'':8}",
        f"  {'':18} {label_a:>8}     {label_b:<8}",
        "",
        row("Win Rate %",      a.get("win_rate",0),     b.get("win_rate",0),     "{:.1f}"),
        row("Avg RR",          a.get("avg_rr",0),       b.get("avg_rr",0),       "{:.2f}"),
        row("Profit Factor",   a.get("profit_factor",0),b.get("profit_factor",0),"{:.2f}"),
        row("Expectancy",      a.get("expectancy",0),   b.get("expectancy",0),   "{:+.3f}"),
        row("Max Drawdown",    a.get("max_drawdown",0), b.get("max_drawdown",0), "{:.2f}", False),
        row("Sharpe",          a.get("sharpe",0),       b.get("sharpe",0),       "{:.2f}"),
        row("30d Win Rate",    a.get("rolling_30d_wr",0),b.get("rolling_30d_wr",0),"{:.1f}"),
        row("90d Win Rate",    a.get("rolling_90d_wr",0),b.get("rolling_90d_wr",0),"{:.1f}"),
        row("Vol Adj Score",   a.get("vol_adj_score",0),b.get("vol_adj_score",0),"{:.1f}"),
        row("Total Trades",    a.get("total_trades",0), b.get("total_trades",0), "{:.0f}"),
        row("Avg Confidence",  a.get("avg_confidence",0),b.get("avg_confidence",0),"{:.1f}"),
        "",
        "◀ = left strategy wins   ▶ = right wins   = = tied",
        "",
    ]

    for strat_key, s in ((s1, a), (s2, b)):
        regime = s.get("regime_stats", {})
        if regime:
            lines.append(f"Regime Breakdown — {s.get('label', strat_key.upper())}:")
            for rname, rd in regime.items():
                if rd["trades"] >= 3:
                    lines.append(f"  {rname:<14} {rd['win_rate']:.0f}% WR  {rd['total_pnl']:+.1f}pts  ({rd['trades']} trades)")
            lines.append("")

    best_tf_a = _best_timeframe(s1, all_stats)
    best_tf_b = _best_timeframe(s2, all_stats)
    lines.append(f"Best Timeframe:")
    lines.append(f"  {label_a}: {best_tf_a}")
    lines.append(f"  {label_b}: {best_tf_b}")

    return "\n".join(lines)


def _best_timeframe(strategy: str, all_stats: dict) -> str:
    """Find best timeframe for a strategy from backtest_runs."""
    import storage.database as db
    runs = db.get_backtest_runs(limit=200)
    strat_runs = [r for r in runs if r["strategy"] == strategy]
    if not strat_runs:
        return "No data"
    by_tf: dict[str, list[float]] = {}
    for r in strat_runs:
        tf = r["timeframe"]
        by_tf.setdefault(tf, []).append(r["win_rate"])
    avg_by_tf = {tf: sum(wrs) / len(wrs) for tf, wrs in by_tf.items()}
    return max(avg_by_tf, key=lambda k: avg_by_tf[k]) if avg_by_tf else "Unknown"


# ── /optimize ────────────────────────────────────────────────────────────────────

async def cmd_optimize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Run parameter optimization for a strategy.
    Usage: /optimize [fib|smc|confluence] [1H|4H] [30d|60d]
    """
    args = context.args or []

    strategy  = args[0].lower().replace("fibonacci", "fib") if args else "fib"
    timeframe = args[1].upper() if len(args) > 1 else "1H"
    lookback  = args[2].lower() if len(args) > 2 else "30d"

    if strategy not in VALID_STRATEGIES:
        await update.message.reply_text(
            f"Unknown strategy '{strategy}'.\n"
            "Valid: fib, smc, confluence\n\n"
            "Usage: /optimize fib 1H 30d",
            reply_markup=back_to_menu(),
        )
        return

    if timeframe in ("15M",):
        timeframe = "15m"

    status = await update.message.reply_text(
        f"Optimizing {strategy.upper()} parameters on {timeframe} ({lookback})…\n"
        "Testing parameter grid — this takes 30-90 seconds…"
    )
    try:
        from analytics.optimizer import run_optimization, format_optimizer_text

        result = run_optimization(strategy, timeframe, lookback)

        if "error" in result:
            await status.edit_text(f"Optimizer error: {result['error']}")
            return

        text = format_optimizer_text(result)

        await status.delete()

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_optimize error: %s", e, exc_info=True)
        await status.edit_text(f"Optimizer error: {e}")
