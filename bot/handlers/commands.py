"""
bot/handlers/commands.py — Slash command handlers.

All slash commands remain functional alongside inline buttons.
"""
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

import storage.database as db
from market.data import fetch_gold_data
from charts.chart_generator import generate_base_chart
from ai.ai_router import generate_signal, generate_summary, generate_alert_commentary
from ai.prompts import build_mtf_prompt, build_summary_prompt
from bot.keyboards.menus import main_menu, back_to_menu
from signals.confluence import calculate_confluence
from strategies.session import analyze_session

logger = logging.getLogger(__name__)

conversation_history: dict[int, list[dict]] = {}


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _core_analyze(chat_id: int) -> str:
    data = fetch_gold_data()
    if not data:
        return "Could not fetch gold price data. Please try again later."
    mode = db.get_ai_mode(chat_id)
    prompt = build_mtf_prompt(data)
    return generate_signal(prompt, mode)


async def _core_chart(data: dict | None = None) -> tuple:
    if data is None:
        data = fetch_gold_data()
    if not data:
        return None, "Could not fetch chart data."
    try:
        buf = generate_base_chart(
            data["df"],
            data["price"],
            data["h1_support"],
            data["h1_resistance"],
        )
        caption = (
            f"XAUUSD  •  48h Chart\n"
            f"Price: {data['price']}\n"
            f"1H  S: {data['h1_support']}  R: {data['h1_resistance']}\n"
            f"4H  {data['h4_trend']}  |  Daily  {data['d1_momentum']}\n"
            f"Alignment: {data['alignment']}"
        )
        return buf, caption
    except Exception as e:
        logger.error("Chart generation error: %s", e)
        return None, "Failed to generate chart."


def _build_summary_message(data: dict, sched_time: str) -> str:
    session_data = analyze_session(data["h1_df"], data["h4_df"])
    from signals.confluence import calculate_confluence
    conf = calculate_confluence(data, data["h1_df"], session_data=session_data)
    from ai.prompts import build_summary_prompt
    prompt = build_summary_prompt(data, conf["total"], session_data)
    mode = "institutional"
    ai_text = generate_summary(prompt, mode)

    conf_bar = "█" * int(conf["total"] // 10) + "░" * (10 - int(conf["total"] // 10))

    return (
        f"XAUUSD Daily Summary\n"
        f"{'─' * 28}\n\n"
        f"Price: {data['price']}\n\n"
        f"1H Bias:        {data['h1_bias']} ({data['h1_pct']:+.2f}%)\n"
        f"4H Trend:       {data['h4_trend']} ({data['h4_pct']:+.2f}%)\n"
        f"Daily Momentum: {data['d1_momentum']} ({data['d1_pct']:+.2f}%)\n"
        f"Alignment:      {data['alignment']}\n\n"
        f"Support:    {data['h1_support']}\n"
        f"Resistance: {data['h1_resistance']}\n\n"
        f"Session: {session_data['current_session']}\n"
        f"Confluence: [{conf_bar}] {conf['total']:.0f}/100\n"
        f"{'─' * 28}\n\n"
        f"{ai_text}\n\n"
        f"{'─' * 28}\n"
        f"Scheduled: {sched_time}"
    )


# ── Command handlers ────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    db.upsert_user(chat_id, user.first_name or "", user.username or "")
    conversation_history.pop(chat_id, None)
    await update.message.reply_text(
        f"Welcome, {user.first_name}.\n\n"
        "XAUUSD Gold AI Assistant\n"
        "Multi-timeframe  •  Fibonacci  •  Smart Money  •  Sessions\n\n"
        "Select an action:",
        reply_markup=main_menu(),
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversation_history.pop(update.effective_chat.id, None)
    await update.message.reply_text("Conversation cleared.", reply_markup=back_to_menu())


async def cmd_gold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = fetch_gold_data()
    if not data:
        await update.message.reply_text("Could not fetch gold price. Try again later.")
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await update.message.reply_text(
        f"XAUUSD  —  Live Price\n\n"
        f"💰 {data['price']}\n\n"
        f"1H  {data['h1_bias']}  ({data['h1_pct']:+.2f}%)\n"
        f"4H  {data['h4_trend']}  ({data['h4_pct']:+.2f}%)\n"
        f"Daily  {data['d1_momentum']}\n"
        f"Alignment: {data['alignment']}\n\n"
        f"S: {data['h1_support']}  |  R: {data['h1_resistance']}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📈 Full Analysis", callback_data="action_analyze"),
                InlineKeyboardButton("📊 Chart",         callback_data="action_chart"),
            ],
            [InlineKeyboardButton("⬅️ Main Menu",         callback_data="menu_main")],
        ]),
    )


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    status = await update.message.reply_text("⏳ Fetching live XAUUSD data…")
    reply = await _core_analyze(chat_id)
    await status.delete()
    from bot.keyboards.menus import after_analysis_menu
    await update.message.reply_text(reply, reply_markup=after_analysis_menu())


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status = await update.message.reply_text("⏳ Generating chart…")
    buf, caption = await _core_chart()
    await status.delete()
    if buf is None:
        await update.message.reply_text(caption, reply_markup=back_to_menu())
    else:
        await update.message.reply_photo(photo=buf, caption=caption, reply_markup=back_to_menu())


async def cmd_fibonacci(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.keyboards.menus import fib_timeframe_menu
    await update.message.reply_text(
        "📐 Fibonacci Analysis\n\nSelect timeframe:",
        reply_markup=fib_timeframe_menu(),
    )


async def cmd_smc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.keyboards.menus import smc_timeframe_menu
    await update.message.reply_text(
        "🏦 Smart Money Concepts\n\nSelect timeframe:",
        reply_markup=smc_timeframe_menu(),
    )


async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text(
            "Usage:\n/alert above 3250\n/alert below 3200\n\n"
            "Sets a price alert. Checks every 60 seconds."
        )
        return

    direction = args[0].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text("Direction must be 'above' or 'below'.")
        return

    try:
        target_price = float(args[1])
    except ValueError:
        await update.message.reply_text("Price must be a number, e.g. /alert above 3250")
        return

    alert_id = db.add_alert(chat_id, direction, target_price)
    arrow = "▲" if direction == "above" else "▼"
    await update.message.reply_text(
        f"Alert #{alert_id} set!\n\n"
        f"{arrow} Notify when XAUUSD goes {direction} {target_price}\n\n"
        "Checks every 60 seconds.",
        reply_markup=back_to_menu(),
    )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_alerts = db.get_alerts(chat_id)
    if not user_alerts:
        await update.message.reply_text(
            "No active alerts.\n\nSet one with:\n/alert above 3250\n/alert below 3200",
            reply_markup=back_to_menu(),
        )
        return
    lines = ["Active XAUUSD Alerts:\n"]
    for a in user_alerts:
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(f"{arrow} {a['direction'].capitalize()} {a['price']}  (ID #{a['id']})")
    lines.append("\nUse /clearalerts to remove all.")
    await update.message.reply_text("\n".join(lines), reply_markup=back_to_menu())


async def cmd_clearalerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = db.clear_alerts(update.effective_chat.id)
    msg = f"Cleared {count} alert(s)." if count else "No active alerts to clear."
    await update.message.reply_text(msg, reply_markup=back_to_menu())


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        status = await update.message.reply_text("⏳ Generating your XAUUSD summary…")
        data = fetch_gold_data()
        if not data:
            await status.edit_text("Could not fetch data. Please try again.")
            return
        sched = db.get_summary_schedule(chat_id) or "now"
        msg = _build_summary_message(data, sched)
        await status.delete()
        await update.message.reply_text(msg, reply_markup=back_to_menu())
        return

    time_str = args[0].strip()
    try:
        t = datetime.strptime(time_str, "%H:%M")
        formatted = t.strftime("%H:%M")
    except ValueError:
        await update.message.reply_text("Invalid time format. Use HH:MM, e.g. /summary 08:00")
        return

    db.set_summary_schedule(chat_id, formatted)
    await update.message.reply_text(
        f"Daily summary scheduled for {formatted} UTC.\n\nUse /summaryoff to disable.",
        reply_markup=back_to_menu(),
    )


async def cmd_summaryoff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if db.get_summary_schedule(chat_id):
        db.delete_summary_schedule(chat_id)
        await update.message.reply_text("Daily summary disabled.", reply_markup=back_to_menu())
    else:
        await update.message.reply_text(
            "No daily summary scheduled.\n\nSet one with: /summary 08:00",
            reply_markup=back_to_menu(),
        )


# ── Background jobs ────────────────────────────────────────────────────────────

async def check_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = fetch_gold_data()
    if not data:
        return
    price = data["price"]

    for alert in db.get_all_active_alerts():
        alert_id = alert["id"]
        chat_id = alert["chat_id"]
        direction = alert["direction"]
        target = alert["price"]

        triggered = (direction == "above" and price >= target) or (direction == "below" and price <= target)
        if not triggered:
            continue

        db.mark_alert_triggered(alert_id)

        try:
            commentary = generate_alert_commentary(price, direction, target)
        except Exception:
            commentary = ""

        arrow = "▲" if direction == "above" else "▼"
        msg = (
            f"ALERT TRIGGERED\n\n"
            f"{arrow} XAUUSD is {direction} {target}\n"
            f"Current price: {price}\n\n"
            f"{commentary}"
        )
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            logger.error("Failed to send alert to %s: %s", chat_id, e)


async def check_summaries(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc)
    current_time = now.strftime("%H:%M")
    current_date = now.strftime("%Y-%m-%d")

    for sched in db.get_all_summary_schedules():
        chat_id = sched["chat_id"]
        sched_time = sched["time_utc"]
        last_sent = sched.get("last_sent") or ""

        if current_time != sched_time:
            continue
        if last_sent.startswith(current_date):
            continue

        db.update_summary_last_sent(chat_id, f"{current_date} {current_time}")

        data = fetch_gold_data()
        if not data:
            continue

        msg = _build_summary_message(data, sched_time)
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg)
        except Exception as e:
            logger.error("Failed to send summary to %s: %s", chat_id, e)


# ── Message handler ────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    chat_id = update.effective_chat.id
    lower = text.lower().strip()

    pending = context.user_data.get("awaiting_alert")
    if pending in ("above", "below"):
        raw = text.strip().replace(",", "")
        try:
            target_price = float(raw)
        except ValueError:
            await update.message.reply_text(
                "Please reply with a number, e.g. 3250",
                reply_markup=back_to_menu(),
            )
            return
        context.user_data.pop("awaiting_alert")
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        alert_id = db.add_alert(chat_id, pending, target_price)
        arrow = "▲" if pending == "above" else "▼"
        await update.message.reply_text(
            f"Alert #{alert_id} set!\n\n{arrow} Notify when XAUUSD goes {pending} {target_price}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Manage Alerts", callback_data="menu_alerts")],
                [InlineKeyboardButton("⬅️ Main Menu",     callback_data="menu_main")],
            ]),
        )
        return

    if any(kw in lower for kw in ["analyze", "signal", "analysis"]):
        await cmd_analyze(update, context)
        return
    if any(kw in lower for kw in ["chart", "candle"]):
        await cmd_chart(update, context)
        return
    if any(kw in lower for kw in ["price", "gold", "xauusd", "rate"]):
        await cmd_gold(update, context)
        return

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    conversation_history[chat_id].append({"role": "user", "content": text})

    from ai.ai_router import chat_response
    mode = db.get_ai_mode(chat_id)
    reply = chat_response(conversation_history[chat_id], mode=mode)
    conversation_history[chat_id].append({"role": "assistant", "content": reply})

    if len(conversation_history[chat_id]) > 20:
        conversation_history[chat_id] = conversation_history[chat_id][-20:]

    await update.message.reply_text(reply, reply_markup=back_to_menu())
