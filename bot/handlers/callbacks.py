"""
bot/handlers/callbacks.py — Inline keyboard callback handler.

Routes all callback_data values to the appropriate action.
"""
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import storage.database as db
from market.data import fetch_gold_data
from bot.keyboards import menus
from bot.handlers.commands import (
    _core_analyze,
    _core_chart,
    _build_summary_message,
    conversation_history,
)

logger = logging.getLogger(__name__)

_HELP_TEXT = (
    "XAUUSD Gold Assistant — Commands\n\n"
    "📈 /analyze  — Multi-timeframe AI signal\n"
    "📊 /chart    — 48h candlestick chart\n"
    "💰 /gold     — Live price + TF snapshot\n"
    "📐 /fibonacci — Fibonacci analysis\n"
    "🏦 /smc      — Smart Money Concepts\n\n"
    "🔔 Alerts\n"
    "/alert above 3250  — Alert above price\n"
    "/alert below 3200  — Alert below price\n"
    "/alerts             — List active alerts\n"
    "/clearalerts        — Remove all alerts\n\n"
    "📰 Daily Summary\n"
    "/summary 08:00  — Schedule daily recap (UTC)\n"
    "/summaryoff     — Disable daily recap\n\n"
    "⚙️ Other\n"
    "/clear  — Reset conversation history\n"
    "/start  — Show main menu\n\n"
    "You can also chat freely — I'll respond as an institutional analyst."
)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # ── Navigation ─────────────────────────────────────────────────────────────
    if data == "menu_main":
        await query.edit_message_text(
            "XAUUSD Gold AI Assistant\n\nSelect an action:",
            reply_markup=menus.main_menu(),
        )

    elif data == "menu_alerts":
        user_alerts = db.get_alerts(chat_id)
        count_line = f"{len(user_alerts)} active alert(s)" if user_alerts else "No active alerts"
        await query.edit_message_text(
            f"🔔 Alerts\n\n{count_line}\n\nSelect an action:",
            reply_markup=menus.alerts_menu(chat_id),
        )

    elif data == "menu_summary":
        sched = db.get_summary_schedule(chat_id)
        sched_line = f"Scheduled: {sched} UTC" if sched else "No schedule set"
        await query.edit_message_text(
            f"📰 Daily Summary\n\n{sched_line}\n\nSelect an action:",
            reply_markup=menus.summary_menu(chat_id),
        )

    elif data == "menu_settings":
        await query.edit_message_text(
            "⚙️ Settings\n\nCurrent configuration:",
            reply_markup=menus.settings_menu(chat_id),
        )

    elif data == "menu_ai_mode":
        mode = db.get_ai_mode(chat_id)
        await query.edit_message_text(
            f"🤖 AI Mode\n\nCurrent: {menus.AI_MODE_LABELS.get(mode, mode)}\n\n"
            "Each mode changes tone, depth, and timeframe emphasis:",
            reply_markup=menus.ai_mode_menu(chat_id),
        )

    elif data == "action_summary_times":
        await query.edit_message_text(
            "📅 Choose daily summary time (UTC):",
            reply_markup=menus.summary_times_menu(),
        )

    # ── Fast actions (no network) ───────────────────────────────────────────────
    elif data == "action_help":
        await query.edit_message_text(_HELP_TEXT, reply_markup=menus.back_to_menu())

    elif data == "action_clear":
        conversation_history.pop(chat_id, None)
        await query.edit_message_text("Conversation cleared.", reply_markup=menus.back_to_menu())

    elif data.startswith("action_set_ai_mode_"):
        mode = data.replace("action_set_ai_mode_", "")
        db.set_ai_mode(chat_id, mode)
        label = menus.AI_MODE_LABELS.get(mode, mode)
        await query.edit_message_text(
            f"AI mode set to {label}.\n\nAll future analyses and chat responses will use this tone.",
            reply_markup=menus.back_to_menu(),
        )

    elif data == "action_alert_list":
        user_alerts = db.get_alerts(chat_id)
        if not user_alerts:
            text = "No active alerts.\n\nUse the buttons below to set one."
        else:
            lines = ["Active XAUUSD Alerts:\n"]
            for a in user_alerts:
                arrow = "▲" if a["direction"] == "above" else "▼"
                lines.append(f"{arrow} {a['direction'].capitalize()} {a['price']}  (ID #{a['id']})")
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=menus.alerts_menu(chat_id))

    elif data == "action_alert_clear":
        count = db.clear_alerts(chat_id)
        msg = f"Cleared {count} alert(s)." if count else "No active alerts to clear."
        await query.edit_message_text(msg, reply_markup=menus.alerts_menu(chat_id))

    elif data == "action_alert_above":
        context.user_data["awaiting_alert"] = "above"
        await query.edit_message_text(
            "▲ Alert Above\n\nReply with the target price level.\n\nExample: 3300",
            reply_markup=menus.back_to_menu(),
        )

    elif data == "action_alert_below":
        context.user_data["awaiting_alert"] = "below"
        await query.edit_message_text(
            "▼ Alert Below\n\nReply with the target price level.\n\nExample: 3200",
            reply_markup=menus.back_to_menu(),
        )

    elif data == "action_summary_off":
        db.delete_summary_schedule(chat_id)
        await query.edit_message_text("Daily summary disabled.", reply_markup=menus.summary_menu(chat_id))

    elif data.startswith("action_summary_set_"):
        time_str = data.replace("action_summary_set_", "")
        db.set_summary_schedule(chat_id, time_str)
        await query.edit_message_text(
            f"✅ Daily summary scheduled for {time_str} UTC.",
            reply_markup=menus.summary_menu(chat_id),
        )

    # ── Fibonacci timeframe selection ───────────────────────────────────────────
    elif data in ("action_fibonacci", "fib_back"):
        await query.edit_message_text(
            "📐 Fibonacci Analysis\n\nSelect timeframe:",
            reply_markup=menus.fib_timeframe_menu(),
        )

    elif data.startswith("fib_tf_"):
        tf = data.replace("fib_tf_", "")
        await query.edit_message_text(f"⏳ Running Fibonacci analysis ({tf.upper()})…")
        await _run_fibonacci(query, chat_id, tf)

    # ── SMC timeframe selection ─────────────────────────────────────────────────
    elif data in ("action_smc", "smc_back"):
        await query.edit_message_text(
            "🏦 Smart Money Concepts\n\nSelect timeframe:",
            reply_markup=menus.smc_timeframe_menu(),
        )

    elif data.startswith("smc_tf_"):
        tf = data.replace("smc_tf_", "")
        await query.edit_message_text(f"⏳ Running SMC analysis ({tf.upper()})…")
        await _run_smc(query, chat_id, tf)

    # ── Heavy actions (fetch + compute + AI) ────────────────────────────────────
    elif data == "action_analyze":
        await query.edit_message_text("⏳ Fetching live XAUUSD data…")
        reply = await _core_analyze(chat_id)
        await query.message.reply_text(reply, reply_markup=menus.after_analysis_menu())

    elif data == "action_chart":
        await query.edit_message_text("⏳ Generating chart…")
        buf, caption = await _core_chart()
        if buf is None:
            await query.message.reply_text(caption, reply_markup=menus.back_to_menu())
        else:
            await query.message.reply_photo(photo=buf, caption=caption, reply_markup=menus.back_to_menu())

    elif data == "action_price":
        await query.edit_message_text("⏳ Fetching live price…")
        data_live = fetch_gold_data()
        if not data_live:
            await query.message.reply_text("Could not fetch price.", reply_markup=menus.back_to_menu())
        else:
            await query.message.reply_text(
                f"XAUUSD  —  Live Price\n\n"
                f"💰 {data_live['price']}\n\n"
                f"1H  {data_live['h1_bias']}  ({data_live['h1_pct']:+.2f}%)\n"
                f"4H  {data_live['h4_trend']}  ({data_live['h4_pct']:+.2f}%)\n"
                f"Daily  {data_live['d1_momentum']}\n"
                f"Alignment: {data_live['alignment']}\n\n"
                f"S: {data_live['h1_support']}  |  R: {data_live['h1_resistance']}",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("📈 Analyze",    callback_data="action_analyze"),
                        InlineKeyboardButton("📊 Chart",      callback_data="action_chart"),
                    ],
                    [InlineKeyboardButton("⬅️ Main Menu",      callback_data="menu_main")],
                ]),
            )

    elif data == "action_sessions":
        await query.edit_message_text("⏳ Analyzing trading sessions…")
        await _run_sessions(query, chat_id)

    elif data == "action_confluence":
        await query.edit_message_text("⏳ Computing confluence score…")
        await _run_confluence(query, chat_id)

    elif data == "action_summary_now":
        await query.edit_message_text("⏳ Generating summary…")
        data_live = fetch_gold_data()
        if not data_live:
            await query.message.reply_text("Could not fetch data.", reply_markup=menus.back_to_menu())
        else:
            sched_time = db.get_summary_schedule(chat_id) or "now"
            msg = _build_summary_message(data_live, sched_time)
            await query.message.reply_text(msg, reply_markup=menus.back_to_menu())


# ── Strategy runners ───────────────────────────────────────────────────────────

async def _run_fibonacci(query, chat_id: int, tf: str) -> None:
    from market.data import fetch_ohlcv
    from strategies.fibonacci import run_fibonacci_analysis, format_fib_text
    from charts.chart_generator import generate_fib_chart
    from ai.ai_router import generate_fib_commentary
    from ai.prompts import build_fib_prompt

    tf_map = {"1h": ("5d", "1h"), "4h": ("30d", "4h"), "daily": ("90d", "1d")}
    period, interval = tf_map.get(tf, ("5d", "1h"))

    df = fetch_ohlcv(period, interval)
    if df is None or len(df) < 20:
        await query.message.reply_text(
            f"Insufficient data for {tf.upper()} Fibonacci analysis.",
            reply_markup=menus.back_to_menu(),
        )
        return

    fib = run_fibonacci_analysis(df, lookback=4 if tf == "1h" else 5)
    if fib is None:
        await query.message.reply_text(
            "Could not detect a clear swing for Fibonacci analysis. Try a different timeframe.",
            reply_markup=menus.fib_timeframe_menu(),
        )
        return

    data = fetch_gold_data() or {"price": float(df["Close"].iloc[-1]), "alignment": "N/A"}
    fib_text = format_fib_text(fib)

    mode = db.get_ai_mode(chat_id)
    prompt = build_fib_prompt(fib, data, mode)
    ai_comment = generate_fib_commentary(prompt, mode)

    full_text = fib_text + "\n\n" + "─" * 28 + "\n\n" + ai_comment

    try:
        buf = generate_fib_chart(df, fib, title=f"XAUUSD  •  Fibonacci ({tf.upper()})")
        caption = f"Fibonacci  ({tf.upper()})  •  Confluence: {fib['confluence_score']:.0f}%"
        await query.message.reply_photo(photo=buf, caption=caption, reply_markup=menus.back_to_menu())
        await query.message.reply_text(full_text, reply_markup=menus.back_to_menu())
    except Exception as e:
        logger.error("Fib chart error: %s", e)
        await query.message.reply_text(full_text, reply_markup=menus.back_to_menu())


async def _run_smc(query, chat_id: int, tf: str) -> None:
    from market.data import fetch_ohlcv
    from strategies.smc import run_smc_analysis, format_smc_text
    from charts.chart_generator import generate_smc_chart
    from ai.ai_router import generate_smc_commentary
    from ai.prompts import build_smc_prompt

    tf_map = {"1h": ("5d", "1h"), "4h": ("30d", "4h"), "daily": ("90d", "1d")}
    period, interval = tf_map.get(tf, ("5d", "1h"))

    df = fetch_ohlcv(period, interval)
    if df is None or len(df) < 15:
        await query.message.reply_text(
            f"Insufficient data for {tf.upper()} SMC analysis.",
            reply_markup=menus.back_to_menu(),
        )
        return

    smc = run_smc_analysis(df, lookback=3 if tf == "1h" else 4)
    smc_text = format_smc_text(smc)

    data = fetch_gold_data() or {"price": smc["price"]}
    mode = db.get_ai_mode(chat_id)
    prompt = build_smc_prompt(smc, data)
    ai_comment = generate_smc_commentary(prompt, mode)

    full_text = smc_text + "\n\n" + "─" * 28 + "\n\n" + ai_comment

    try:
        buf = generate_smc_chart(df, smc, title=f"XAUUSD  •  Smart Money ({tf.upper()})")
        caption = f"Smart Money Concepts  ({tf.upper()})"
        await query.message.reply_photo(photo=buf, caption=caption, reply_markup=menus.back_to_menu())
        await query.message.reply_text(full_text, reply_markup=menus.back_to_menu())
    except Exception as e:
        logger.error("SMC chart error: %s", e)
        await query.message.reply_text(full_text, reply_markup=menus.back_to_menu())


async def _run_sessions(query, chat_id: int) -> None:
    from strategies.session import analyze_session
    from ai.ai_router import generate_session_commentary
    from ai.prompts import build_session_prompt

    data = fetch_gold_data()
    if not data:
        await query.message.reply_text("Could not fetch data.", reply_markup=menus.back_to_menu())
        return

    session_data = analyze_session(data["h1_df"], data["h4_df"])
    ranges = session_data.get("session_ranges", {})

    range_lines = []
    for sess, r in ranges.items():
        if r.get("range") is not None:
            range_lines.append(f"  {sess:12s} {r['low']} – {r['high']}  (range: {r['range']})")
        else:
            range_lines.append(f"  {sess:12s} N/A")

    session_text = (
        f"XAUUSD — Session Intelligence\n\n"
        f"Current Session: {session_data['current_session']}\n"
        f"Session Bias:    {session_data['session_bias']}\n"
        f"Volatility:      {session_data['volatility']}\n\n"
        f"Session Ranges:\n" + "\n".join(range_lines) + "\n\n"
        f"Pattern:\n  {session_data['pattern']}\n\n"
        f"Continuation Probability: {session_data['continuation_pct']:.0f}%\n"
        f"Note: {session_data['bias_note']}"
    )

    mode = db.get_ai_mode(chat_id)
    prompt = build_session_prompt(session_data, data)
    ai_comment = generate_session_commentary(prompt, mode)
    full_text = session_text + "\n\n" + "─" * 28 + "\n\n" + ai_comment

    await query.message.reply_text(full_text, reply_markup=menus.back_to_menu())


async def _run_confluence(query, chat_id: int) -> None:
    from signals.confluence import calculate_confluence, format_confluence_text
    from strategies.fibonacci import run_fibonacci_analysis
    from strategies.smc import run_smc_analysis
    from strategies.session import analyze_session

    data = fetch_gold_data()
    if not data:
        await query.message.reply_text("Could not fetch data.", reply_markup=menus.back_to_menu())
        return

    h1_df = data["h1_df"]
    h4_df = data["h4_df"]

    fib = run_fibonacci_analysis(h1_df, lookback=4)
    smc = run_smc_analysis(h1_df, lookback=3)
    session_data = analyze_session(h1_df, h4_df)

    result = calculate_confluence(data, h1_df, smc_result=smc, fib_result=fib, session_data=session_data)
    conf_text = format_confluence_text(result)

    header = (
        f"Price: {data['price']}\n"
        f"Alignment: {data['alignment']}\n\n"
    )

    await query.message.reply_text(
        header + conf_text,
        reply_markup=menus.after_analysis_menu(),
    )
