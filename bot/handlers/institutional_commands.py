"""
bot/handlers/institutional_commands.py — Institutional expansion commands.

Handles: /backtest, /votes, /heatmap, /debugmulti
All Python-computed. AI only explains final outputs where applicable.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.menus import back_to_menu

logger = logging.getLogger(__name__)


# ── /votes ───────────────────────────────────────────────────────────────────────

async def cmd_votes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run the strategy voting engine and display consensus."""
    status = await update.message.reply_text("Calculating strategy votes…")
    try:
        from market.data import fetch_gold_data
        from strategies.fibonacci import run_fibonacci_analysis
        from strategies.smc import run_smc_analysis
        from strategies.session import analyze_session
        from signals.confluence import calculate_confluence
        from signals.voting import run_vote, format_vote_text

        data = fetch_gold_data()
        if not data:
            await status.edit_text("Could not fetch market data. Try again.")
            return

        df = data["h1_df"]
        fib     = run_fibonacci_analysis(df)
        smc     = run_smc_analysis(df)
        session = analyze_session(data["h1_df"], data["h4_df"])
        conf    = calculate_confluence(data, df, smc_result=smc,
                                       fib_result=fib, session_data=session)

        result = run_vote(
            df=df,
            smc_result=smc,
            fib_result=fib,
            session_data=session,
            confluence_result=conf,
        )

        text = format_vote_text(result)
        await status.delete()
        await update.message.reply_text(text, reply_markup=back_to_menu())

    except Exception as e:
        logger.error("cmd_votes error: %s", e, exc_info=True)
        await status.edit_text(f"Voting engine error: {e}")


# ── /heatmap ─────────────────────────────────────────────────────────────────────

async def cmd_heatmap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate the multi-timeframe strategy heatmap."""
    status = await update.message.reply_text("Building multi-timeframe heatmap…")
    try:
        from signals.heatmap import compute_heatmap, format_heatmap_text, generate_heatmap_chart

        result = compute_heatmap()
        text   = format_heatmap_text(result)
        chart  = generate_heatmap_chart(result)

        await status.delete()
        await update.message.reply_photo(
            photo=chart,
            caption=text[:1024],
            reply_markup=back_to_menu(),
        )

    except Exception as e:
        logger.error("cmd_heatmap error: %s", e, exc_info=True)
        await status.edit_text(f"Heatmap error: {e}")


# ── /backtest ────────────────────────────────────────────────────────────────────

async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Run a historical backtest.

    Usage: /backtest fib|smc|confluence [1H|4H|15m|1D] [30d|60d|90d]
    """
    from backtesting.engine import parse_backtest_args, run_backtest
    from backtesting.metrics import format_metrics_text
    from backtesting.reports import generate_backtest_charts

    args = context.args or []
    strategy, timeframe, lookback, err = parse_backtest_args(args)

    if err:
        await update.message.reply_text(
            f"Backtest\n\n{err}\n\n"
            "Examples:\n"
            "/backtest fib\n"
            "/backtest smc 4H 60d\n"
            "/backtest confluence 1H 90d",
            reply_markup=back_to_menu(),
        )
        return

    status = await update.message.reply_text(
        f"Running backtest: {strategy.upper()} | {timeframe} | {lookback}\n"
        "This may take 20-40 seconds…"
    )

    try:
        metrics, meta, error = run_backtest(strategy, timeframe, lookback)

        if error:
            await status.edit_text(f"Backtest failed: {error}")
            return

        report_text = format_metrics_text(metrics, strategy, timeframe, lookback)
        chart_buf   = generate_backtest_charts(metrics, meta)

        await status.delete()
        await update.message.reply_photo(
            photo=chart_buf,
            caption=report_text[:1024],
            reply_markup=back_to_menu(),
        )

        if len(report_text) > 1024:
            await update.message.reply_text(
                report_text,
                reply_markup=back_to_menu(),
            )

    except Exception as e:
        logger.error("cmd_backtest error: %s", e, exc_info=True)
        await status.edit_text(f"Backtest engine error: {e}")


# ── /debugmulti ──────────────────────────────────────────────────────────────────

async def cmd_debugmulti(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Run all strategy engines across all timeframes and expose raw outputs,
    scores, alignment conflicts, regime conditions, and confidence breakdowns.
    """
    status = await update.message.reply_text("Running multi-timeframe debug analysis…")

    try:
        from market.data import fetch_ohlcv
        from market.regime import detect_regime
        from strategies.fibonacci import run_fibonacci_analysis
        from strategies.smc import run_smc_analysis
        from signals.heatmap import TIMEFRAMES, compute_heatmap
        from signals.voting import _vote_smc, _vote_fibonacci, _vote_momentum, _vote_session, _vote_confluence

        heatmap = compute_heatmap()

        lines = [
            "DEBUGMULTI — Full Institutional Breakdown",
            "=" * 38,
            "",
        ]

        tf_configs = {
            "15m": ("5d",  "15m"),
            "1H":  ("5d",  "1h"),
            "4H":  ("30d", "4h"),
            "D1":  ("90d", "1d"),
        }

        for tf_label, (period, interval) in tf_configs.items():
            df = fetch_ohlcv(period, interval)
            if df is None or df.empty:
                lines.append(f"[{tf_label}] No data available")
                lines.append("")
                continue

            regime = detect_regime(df)
            fib    = run_fibonacci_analysis(df)
            smc    = run_smc_analysis(df)

            smc_v,  smc_c  = _vote_smc(smc)
            fib_v,  fib_c  = _vote_fibonacci(fib)
            mom_v,  mom_c  = _vote_momentum(df)

            lines.append(f"[ {tf_label} ]  —  {regime['label']}")
            lines.append(f"  ATR Pct:    {regime['atr_pct']:.2f}")
            lines.append(f"  EMA Slope:  {regime['ema_slope_pct']:+.4f}%")
            lines.append(f"  BB Width:   {regime['bb_width']:.3f}%")
            lines.append(f"  Trending:   {regime['trending_score']:.2f}")
            lines.append(f"  Ranging:    {regime['ranging_score']:.2f}")
            lines.append("")
            lines.append(f"  SMC Bias:   {smc.get('overall_bias','?')}  →  {smc_v}  ({smc_c:.0f}%)")
            lines.append(f"  FIB Dir:    {fib.get('direction','N/A') if fib else 'N/A'}  →  {fib_v}  ({fib_c:.0f}%)")
            lines.append(f"  Momentum:   {mom_v}  ({mom_c:.0f}%)")
            if fib:
                lines.append(f"  FIB Score:  {fib.get('confluence_score', 0):.0f}/100")
                lines.append(f"  Nearest:    {fib.get('nearest_level', 'N/A')}")
            lines.append(f"  BOS:        {smc.get('bos_count', 0)}")
            lines.append(f"  CHoCH:      {smc.get('choch_count', 0)}")
            lines.append(f"  OBs:        {len(smc.get('order_blocks', []))}")
            lines.append(f"  FVGs:       {len(smc.get('fvg_list', []))}")
            lines.append("")

        lines.append("Heatmap Alignment:")
        for tf, alignment in heatmap.get("alignment_by_tf", {}).items():
            lines.append(f"  {tf:<4}  {alignment}")

        lines.append("")
        lines.append(f"Overall Bias:     {heatmap.get('overall_bias', 'FLAT')}")
        lines.append(f"TF Agreement:     {heatmap.get('trend_agreement_score', 0):.0f}%")
        lines.append(f"Conflict Score:   {heatmap.get('conflict_score', 0):.2f}")

        warnings = heatmap.get("warnings", [])
        if warnings:
            lines.append("")
            for w in warnings:
                lines.append(f"! {w}")

        full_text = "\n".join(lines)

        await status.delete()

        chunk_size = 4000
        for i in range(0, len(full_text), chunk_size):
            chunk = full_text[i:i + chunk_size]
            await update.message.reply_text(chunk, reply_markup=back_to_menu() if i + chunk_size >= len(full_text) else None)

    except Exception as e:
        logger.error("cmd_debugmulti error: %s", e, exc_info=True)
        await status.edit_text(f"Debug error: {e}")
