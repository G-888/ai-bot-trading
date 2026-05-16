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

_STRATS = [
    ("fib",         "📐 Fibonacci"),
    ("smc",         "🏦 Smart Money"),
    ("confluence",  "◆ Confluence"),
]

_TIMEFRAMES = ["15m", "1H", "4H", "1D"]

_RANGES = ["30d", "60d", "90d"]


# ── Shared action rows ────────────────────────────────────────────────────────────

def _refresh_row(refresh_data: str) -> list:
    return [
        InlineKeyboardButton("🔄 Refresh",    callback_data=refresh_data),
        InlineKeyboardButton("🏠 Main Menu",  callback_data="menu_main"),
    ]


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")]
    ])


def refresh_and_menu(refresh_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_refresh_row(refresh_data)])


# ── Main menu ────────────────────────────────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Analyze",      callback_data="action_analyze"),
            InlineKeyboardButton("📊 Chart",         callback_data="action_chart"),
        ],
        [
            InlineKeyboardButton("📐 Fibonacci",     callback_data="action_fibonacci"),
            InlineKeyboardButton("🏦 Smart Money",   callback_data="action_smc"),
        ],
        [
            InlineKeyboardButton("🕐 Sessions",      callback_data="action_sessions"),
            InlineKeyboardButton("◆ Confluence",     callback_data="action_confluence"),
        ],
        [
            InlineKeyboardButton("💰 Live Price",    callback_data="action_price"),
            InlineKeyboardButton("📰 Daily Summary", callback_data="menu_summary"),
        ],
        [
            InlineKeyboardButton("📊 Backtest",      callback_data="menu_backtest"),
            InlineKeyboardButton("🧠 Performance",   callback_data="menu_performance"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard",   callback_data="action_leaderboard"),
            InlineKeyboardButton("🌡 Heatmap",       callback_data="action_heatmap"),
        ],
        [
            InlineKeyboardButton("🗳 Votes",         callback_data="action_votes"),
            InlineKeyboardButton("🩺 Diagnostics",   callback_data="action_diagnostics"),
        ],
        [
            InlineKeyboardButton("🔔 Alerts",        callback_data="menu_alerts"),
            InlineKeyboardButton("⚙️ Settings",      callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("❓ Help",           callback_data="action_help"),
        ],
    ])


# ── Backtest flow ────────────────────────────────────────────────────────────────

def backtest_strategy_menu() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📐 Fibonacci",   callback_data="bt_strat_fib"),
            InlineKeyboardButton("🏦 Smart Money", callback_data="bt_strat_smc"),
        ],
        [
            InlineKeyboardButton("◆ Confluence",   callback_data="bt_strat_confluence"),
        ],
        [InlineKeyboardButton("🏠 Main Menu",      callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(rows)


def backtest_tf_menu(strategy: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("15m", callback_data=f"bt_tf_{strategy}_15m"),
            InlineKeyboardButton("1H",  callback_data=f"bt_tf_{strategy}_1H"),
        ],
        [
            InlineKeyboardButton("4H",  callback_data=f"bt_tf_{strategy}_4H"),
            InlineKeyboardButton("1D",  callback_data=f"bt_tf_{strategy}_1D"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_backtest")],
    ]
    return InlineKeyboardMarkup(rows)


def backtest_range_menu(strategy: str, tf: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("30d", callback_data=f"bt_run_{strategy}_{tf}_30d"),
            InlineKeyboardButton("60d", callback_data=f"bt_run_{strategy}_{tf}_60d"),
            InlineKeyboardButton("90d", callback_data=f"bt_run_{strategy}_{tf}_90d"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"bt_strat_{strategy}")],
    ]
    return InlineKeyboardMarkup(rows)


# ── Performance research hub ──────────────────────────────────────────────────────

def performance_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Performance",  callback_data="action_performance"),
            InlineKeyboardButton("🏆 Leaderboard",  callback_data="action_leaderboard"),
        ],
        [
            InlineKeyboardButton("🩺 Diagnostics",  callback_data="action_diagnostics"),
            InlineKeyboardButton("⚙️ Optimize",     callback_data="menu_optimize"),
        ],
        [
            InlineKeyboardButton("🌡 Heatmap",      callback_data="action_heatmap"),
            InlineKeyboardButton("🗳 Votes",        callback_data="action_votes"),
        ],
        [
            InlineKeyboardButton("📉 Decay",        callback_data="action_decay"),
            InlineKeyboardButton("🔬 Edge Health",  callback_data="action_edge"),
        ],
        [
            InlineKeyboardButton("🕸 Regime Health", callback_data="action_regimehealth"),
            InlineKeyboardButton("📊 Stability",    callback_data="action_stability"),
        ],
        [InlineKeyboardButton("🏠 Main Menu",       callback_data="menu_main")],
    ])


# ── Optimize flow ────────────────────────────────────────────────────────────────

def optimize_strategy_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📐 Fibonacci",   callback_data="opt_strat_fib"),
            InlineKeyboardButton("🏦 Smart Money", callback_data="opt_strat_smc"),
        ],
        [
            InlineKeyboardButton("◆ Confluence",   callback_data="opt_strat_confluence"),
        ],
        [InlineKeyboardButton("⬅️ Back",           callback_data="menu_performance")],
    ])


def optimize_tf_menu(strategy: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1H", callback_data=f"opt_tf_{strategy}_1H"),
            InlineKeyboardButton("4H", callback_data=f"opt_tf_{strategy}_4H"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu_optimize")],
    ])


def optimize_range_menu(strategy: str, tf: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30d", callback_data=f"opt_run_{strategy}_{tf}_30d"),
            InlineKeyboardButton("60d", callback_data=f"opt_run_{strategy}_{tf}_60d"),
            InlineKeyboardButton("90d", callback_data=f"opt_run_{strategy}_{tf}_90d"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"opt_strat_{strategy}")],
    ])


# ── Existing menus (unchanged) ───────────────────────────────────────────────────

def alerts_menu(chat_id: int) -> InlineKeyboardMarkup:
    user_alerts = db.get_alerts(chat_id)
    count = len(user_alerts)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▲ Alert Above",       callback_data="action_alert_above"),
            InlineKeyboardButton("▼ Alert Below",       callback_data="action_alert_below"),
        ],
        [
            InlineKeyboardButton(f"📋 My Alerts ({count})", callback_data="action_alert_list"),
            InlineKeyboardButton("🗑 Clear All",         callback_data="action_alert_clear"),
        ],
        [InlineKeyboardButton("🏠 Main Menu",            callback_data="menu_main")],
    ])


def summary_menu(chat_id: int) -> InlineKeyboardMarkup:
    scheduled = db.get_summary_schedule(chat_id)
    schedule_btn = (
        InlineKeyboardButton(f"✅ {scheduled} UTC — Change", callback_data="action_summary_times")
        if scheduled else
        InlineKeyboardButton("📅 Set Schedule",               callback_data="action_summary_times")
    )
    rows = [
        [schedule_btn],
        [InlineKeyboardButton("📰 Send Summary Now", callback_data="action_summary_now")],
    ]
    if scheduled:
        rows.append([InlineKeyboardButton("⏸ Disable Summary", callback_data="action_summary_off")])
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])
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
        [InlineKeyboardButton("🏠 Main Menu",                callback_data="menu_main")],
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
            InlineKeyboardButton("📊 Chart",       callback_data="action_chart"),
            InlineKeyboardButton("📐 Fibonacci",   callback_data="action_fibonacci"),
        ],
        [
            InlineKeyboardButton("🏦 Smart Money", callback_data="action_smc"),
            InlineKeyboardButton("◆ Confluence",   callback_data="action_confluence"),
        ],
        [InlineKeyboardButton("🏠 Main Menu",      callback_data="menu_main")],
    ])
