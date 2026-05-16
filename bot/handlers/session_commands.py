"""
bot/handlers/session_commands.py — Session performance analytics commands.

Handles: /session [strategy]
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.menus import back_to_menu, refresh_and_menu

logger = logging.getLogger(__name__)

VALID_STRATEGIES = {"fib", "fibonacci", "smc", "confluence"}


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Session performance breakdown per strategy.
    Usage: /session [fib|smc|confluence]
    """
    args     = context.args or []
    strategy = args[0].lower().replace("fibonacci", "fib") if args else None

    if strategy and strategy not in VALID_STRATEGIES:
        await update.message.reply_text(
            f"Unknown strategy '{strategy}'.\nValid: fib, smc, confluence\n\n"
            "Usage:\n"
            "/session          — all strategies\n"
            "/session fib      — Fibonacci only\n"
            "/session smc      — SMC only\n"
            "/session confluence",
            reply_markup=back_to_menu(),
        )
        return

    target = strategy.upper() if strategy else "all strategies"
    status = await update.message.reply_text(
        f"Analysing session performance for {target}…\n"
        "Classifying trades by London / New York / Asia / Overlap…"
    )

    try:
        from analytics.session_analytics import (
            run_session_analysis,
            format_session_report,
            generate_session_chart,
        )

        analysis = run_session_analysis()

        if not analysis:
            await status.edit_text(
                "No backtest data for session analysis.\n\n"
                "Run backtests first:\n"
                "/backtest fib 1H 30d\n"
                "/backtest smc 1H 30d\n"
                "/backtest confluence 1H 30d",
                reply_markup=back_to_menu(),
            )
            return

        chart  = generate_session_chart(
            {strategy: analysis[strategy]} if strategy and strategy in analysis else analysis
        )
        text   = format_session_report(analysis, strategy=strategy)

        await status.delete()

        await update.message.reply_photo(
            photo=chart,
            caption=f"Session Analytics — {target.upper()}",
            reply_markup=refresh_and_menu("action_session_analytics"),
        )

        chunk = 4000
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=refresh_and_menu("action_session_analytics") if is_last else None,
            )

    except Exception as e:
        logger.error("cmd_session error: %s", e, exc_info=True)
        await status.edit_text(f"Session analysis error: {e}")
