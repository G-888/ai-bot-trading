"""
main.py — XAUUSD Gold AI Trading Assistant
Entry point. All logic lives in the modules under bot/, market/, strategies/, etc.
"""
import logging
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from storage.database import init_db
from bot.handlers.commands import (
    cmd_start,
    cmd_clear,
    cmd_gold,
    cmd_analyze,
    cmd_chart,
    cmd_fibonacci,
    cmd_smc,
    cmd_alert,
    cmd_alerts,
    cmd_clearalerts,
    cmd_summary,
    cmd_summaryoff,
    handle_message,
    check_alerts,
    check_summaries,
)
from bot.handlers.callbacks import button_callback
from bot.handlers.debug_commands import (
    cmd_debugfib,
    cmd_debugsmc,
    cmd_debugconfluence,
)
from bot.handlers.institutional_commands import (
    cmd_votes,
    cmd_heatmap,
    cmd_backtest,
    cmd_debugmulti,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    init_db()

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("clear",       cmd_clear))
    app.add_handler(CommandHandler("gold",        cmd_gold))
    app.add_handler(CommandHandler("xauusd",      cmd_gold))
    app.add_handler(CommandHandler("analyze",     cmd_analyze))
    app.add_handler(CommandHandler("chart",       cmd_chart))
    app.add_handler(CommandHandler("fibonacci",   cmd_fibonacci))
    app.add_handler(CommandHandler("fib",         cmd_fibonacci))
    app.add_handler(CommandHandler("smc",         cmd_smc))
    app.add_handler(CommandHandler("alert",       cmd_alert))
    app.add_handler(CommandHandler("alerts",      cmd_alerts))
    app.add_handler(CommandHandler("clearalerts", cmd_clearalerts))
    app.add_handler(CommandHandler("summary",        cmd_summary))
    app.add_handler(CommandHandler("summaryoff",     cmd_summaryoff))

    app.add_handler(CommandHandler("debugfib",        cmd_debugfib))
    app.add_handler(CommandHandler("debugsmc",        cmd_debugsmc))
    app.add_handler(CommandHandler("debugconfluence", cmd_debugconfluence))

    app.add_handler(CommandHandler("votes",           cmd_votes))
    app.add_handler(CommandHandler("heatmap",         cmd_heatmap))
    app.add_handler(CommandHandler("backtest",        cmd_backtest))
    app.add_handler(CommandHandler("debugmulti",      cmd_debugmulti))

    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(check_alerts,    interval=60, first=15)
    app.job_queue.run_repeating(check_summaries, interval=60, first=20)

    logger.info("Gold Trading Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
