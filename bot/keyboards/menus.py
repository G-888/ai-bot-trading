"""
bot/keyboards/menus.py — All inline keyboard builders.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import storage.database as db

AI_MODE_LABELS = {
    "institutional": "🏛 Institutional",
    "scalper":       "⚡ Scalper",
    "swing":         "📐 Swing Trader",
    "macro":         "🌐 Macro Analyst",
}


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Analyze",        callback_data="action_analyze"),
            InlineKeyboardButton("📊 Chart",           callback_data="action_chart"),
        ],
        [
            InlineKeyboardButton("📐 Fibonacci",       callback_data="action_fibonacci"),
            InlineKeyboardButton("🏦 Smart Money",     callback_data="action_smc"),
        ],
        [
            InlineKeyboardButton("🕐 Sessions",        callback_data="action_sessions"),
            InlineKeyboardButton("◆ Confluence",       callback_data="action_confluence"),
        ],
        [
            InlineKeyboardButton("💰 Live Price",      callback_data="action_price"),
            InlineKeyboardButton("📰 Daily Summary",   callback_data="menu_summary"),
        ],
        [
            InlineKeyboardButton("🔔 Alerts",          callback_data="menu_alerts"),
            InlineKeyboardButton("⚙️ Settings",        callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("❓ Help",             callback_data="action_help"),
        ],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Main Menu", callback_data="menu_main")]])


def alerts_menu(chat_id: int) -> InlineKeyboardMarkup:
    user_alerts = db.get_alerts(chat_id)
    count = len(user_alerts)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▲ Alert Above",      callback_data="action_alert_above"),
            InlineKeyboardButton("▼ Alert Below",      callback_data="action_alert_below"),
        ],
        [
            InlineKeyboardButton(f"📋 My Alerts ({count})", callback_data="action_alert_list"),
            InlineKeyboardButton("🗑 Clear All",        callback_data="action_alert_clear"),
        ],
        [InlineKeyboardButton("⬅️ Main Menu",           callback_data="menu_main")],
    ])


def summary_menu(chat_id: int) -> InlineKeyboardMarkup:
    scheduled = db.get_summary_schedule(chat_id)
    schedule_btn = (
        InlineKeyboardButton(f"✅ {scheduled} UTC — Change", callback_data="action_summary_times")
        if scheduled else
        InlineKeyboardButton("📅 Set Schedule",              callback_data="action_summary_times")
    )
    rows = [
        [schedule_btn],
        [InlineKeyboardButton("📰 Send Summary Now",     callback_data="action_summary_now")],
    ]
    if scheduled:
        rows.append([InlineKeyboardButton("⏸ Disable Summary", callback_data="action_summary_off")])
    rows.append([InlineKeyboardButton("⬅️ Main Menu",     callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def summary_times_menu() -> InlineKeyboardMarkup:
    times = ["05:00", "07:00", "08:00", "10:00", "12:00", "16:00", "18:00", "20:00"]
    rows = [
        [InlineKeyboardButton(f"🕐 {t} UTC", callback_data=f"action_summary_set_{t}") for t in times[i:i+2]]
        for i in range(0, len(times), 2)
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_summary")])
    return InlineKeyboardMarkup(rows)


def settings_menu(chat_id: int) -> InlineKeyboardMarkup:
    sched = db.get_summary_schedule(chat_id) or "Off"
    alert_count = len(db.get_alerts(chat_id))
    ai_mode = db.get_ai_mode(chat_id)
    mode_label = AI_MODE_LABELS.get(ai_mode, ai_mode)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 AI Mode: {mode_label}",  callback_data="menu_ai_mode")],
        [InlineKeyboardButton(f"📰 Summary: {sched} UTC",   callback_data="menu_summary")],
        [InlineKeyboardButton(f"🔔 Alerts: {alert_count}",  callback_data="menu_alerts")],
        [InlineKeyboardButton("🗑 Clear Conversation",       callback_data="action_clear")],
        [InlineKeyboardButton("⬅️ Main Menu",                callback_data="menu_main")],
    ])


def ai_mode_menu(chat_id: int) -> InlineKeyboardMarkup:
    current = db.get_ai_mode(chat_id)
    rows = []
    for mode, label in AI_MODE_LABELS.items():
        tick = " ✅" if mode == current else ""
        rows.append([InlineKeyboardButton(label + tick, callback_data=f"action_set_ai_mode_{mode}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(rows)


def fib_timeframe_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1H",    callback_data="fib_tf_1h"),
            InlineKeyboardButton("4H",    callback_data="fib_tf_4h"),
            InlineKeyboardButton("Daily", callback_data="fib_tf_daily"),
        ],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="menu_main")],
    ])


def smc_timeframe_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1H",    callback_data="smc_tf_1h"),
            InlineKeyboardButton("4H",    callback_data="smc_tf_4h"),
            InlineKeyboardButton("Daily", callback_data="smc_tf_daily"),
        ],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="menu_main")],
    ])


def after_analysis_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Chart",        callback_data="action_chart"),
            InlineKeyboardButton("📐 Fibonacci",    callback_data="action_fibonacci"),
        ],
        [
            InlineKeyboardButton("🏦 Smart Money",  callback_data="action_smc"),
            InlineKeyboardButton("◆ Confluence",    callback_data="action_confluence"),
        ],
        [InlineKeyboardButton("⬅️ Main Menu",        callback_data="menu_main")],
    ])
