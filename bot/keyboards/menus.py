"""
bot/keyboards/menus.py — All inline keyboard builders.

4-section institutional menu structure:
  📈 Trading  |  🧠 Analytics  |  📚 Research  |  ⚙️ System
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import storage.database as db

AI_MODE_LABELS = {
    "institutional": "🏛 Institutional",
    "scalper":       "⚡ Scalper",
    "swing":         "📐 Swing Trader",
    "macro":         "🌐 Macro Analyst",
}


# ── Shared navigation helpers ─────────────────────────────────────────────────────

def _nav_row(back_data: str, refresh_data: str | None = None) -> list:
    row = []
    if refresh_data:
        row.append(InlineKeyboardButton("🔄 Refresh", callback_data=refresh_data))
    row.append(InlineKeyboardButton("🔙 Back",     callback_data=back_data))
    row.append(InlineKeyboardButton("🏠 Home",     callback_data="menu_main"))
    return row


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Back",  callback_data="menu_main"),
            InlineKeyboardButton("🏠 Home",  callback_data="menu_main"),
        ]
    ])


def refresh_and_menu(refresh_data: str, back_data: str = "menu_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=refresh_data),
            InlineKeyboardButton("🏠 Home",    callback_data="menu_main"),
        ]
    ])


# ── Main menu — 4 grouped sections ───────────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Trading",   callback_data="menu_trading"),
            InlineKeyboardButton("🧠 Analytics", callback_data="menu_analytics"),
        ],
        [
            InlineKeyboardButton("📚 Research",  callback_data="menu_research"),
            InlineKeyboardButton("⚙️ System",    callback_data="menu_system"),
        ],
    ])


# ── Section submenus ──────────────────────────────────────────────────────────────

def trading_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Analyze",     callback_data="action_analyze"),
            InlineKeyboardButton("📈 Chart",        callback_data="action_chart"),
        ],
        [
            InlineKeyboardButton("📐 Fibonacci",   callback_data="action_fibonacci"),
            InlineKeyboardButton("🏦 Smart Money", callback_data="action_smc"),
        ],
        [
            InlineKeyboardButton("🕐 Sessions",    callback_data="action_sessions"),
            InlineKeyboardButton("◆ Confluence",   callback_data="action_confluence"),
        ],
        [
            InlineKeyboardButton("🗳 Voting",      callback_data="action_votes"),
            InlineKeyboardButton("💰 Live Price",  callback_data="action_price"),
        ],
        [InlineKeyboardButton("🏠 Home",           callback_data="menu_main")],
    ])


def analytics_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Backtest",     callback_data="menu_backtest"),
            InlineKeyboardButton("📈 Performance",  callback_data="action_performance"),
        ],
        [
            InlineKeyboardButton("🩺 Diagnostics", callback_data="action_diagnostics"),
            InlineKeyboardButton("🌡 Heatmap",      callback_data="action_heatmap"),
        ],
        [
            InlineKeyboardButton("📉 Decay",        callback_data="action_decay"),
            InlineKeyboardButton("🏆 Leaderboard",  callback_data="action_leaderboard"),
        ],
        [
            InlineKeyboardButton("⚙️ Optimize",    callback_data="menu_optimize"),
            InlineKeyboardButton("🕐 Sessions",     callback_data="action_session_analytics"),
        ],
        [InlineKeyboardButton("🏠 Home",            callback_data="menu_main")],
    ])


def research_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🕸 Regime Health", callback_data="action_regimehealth"),
            InlineKeyboardButton("🔬 Edge Health",   callback_data="action_edge"),
        ],
        [
            InlineKeyboardButton("📊 Stability",     callback_data="action_stability"),
            InlineKeyboardButton("⚖️ Compare",       callback_data="menu_compare"),
        ],
        [
            InlineKeyboardButton("📋 Weekly Report", callback_data="action_weekly"),
            InlineKeyboardButton("📡 Monitor",       callback_data="action_monitor"),
        ],
        [InlineKeyboardButton("🏠 Home",             callback_data="menu_main")],
    ])


def system_menu(chat_id: int) -> InlineKeyboardMarkup:
    sched       = db.get_summary_schedule(chat_id)
    alert_count = len(db.get_alerts(chat_id))
    ai_mode     = db.get_ai_mode(chat_id)
    mode_label  = AI_MODE_LABELS.get(ai_mode, ai_mode)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🔔 Alerts ({alert_count})", callback_data="menu_alerts"),
            InlineKeyboardButton(f"📰 Summary",                callback_data="menu_summary"),
        ],
        [
            InlineKeyboardButton(f"🤖 {mode_label}",           callback_data="menu_ai_mode"),
            InlineKeyboardButton("⚙️ Settings",               callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("❓ Help",                    callback_data="action_help"),
            InlineKeyboardButton("🗑 Clear Chat",              callback_data="action_clear"),
        ],
        [InlineKeyboardButton("🏠 Home",                       callback_data="menu_main")],
    ])


# ── Backtest flow ─────────────────────────────────────────────────────────────────

def backtest_strategy_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📐 Fibonacci",   callback_data="bt_strat_fib"),
            InlineKeyboardButton("🏦 Smart Money", callback_data="bt_strat_smc"),
        ],
        [
            InlineKeyboardButton("◆ Confluence",   callback_data="bt_strat_confluence"),
        ],
        _nav_row("menu_analytics"),
    ])


def backtest_tf_menu(strategy: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("15m", callback_data=f"bt_tf_{strategy}_15m"),
            InlineKeyboardButton("1H",  callback_data=f"bt_tf_{strategy}_1H"),
        ],
        [
            InlineKeyboardButton("4H",  callback_data=f"bt_tf_{strategy}_4H"),
            InlineKeyboardButton("1D",  callback_data=f"bt_tf_{strategy}_1D"),
        ],
        _nav_row("menu_backtest"),
    ])


def backtest_range_menu(strategy: str, tf: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30d", callback_data=f"bt_run_{strategy}_{tf}_30d"),
            InlineKeyboardButton("60d", callback_data=f"bt_run_{strategy}_{tf}_60d"),
            InlineKeyboardButton("90d", callback_data=f"bt_run_{strategy}_{tf}_90d"),
        ],
        _nav_row(f"bt_strat_{strategy}"),
    ])


# ── Optimize flow ─────────────────────────────────────────────────────────────────

def optimize_strategy_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📐 Fibonacci",   callback_data="opt_strat_fib"),
            InlineKeyboardButton("🏦 Smart Money", callback_data="opt_strat_smc"),
        ],
        [
            InlineKeyboardButton("◆ Confluence",   callback_data="opt_strat_confluence"),
        ],
        _nav_row("menu_analytics"),
    ])


def optimize_tf_menu(strategy: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1H", callback_data=f"opt_tf_{strategy}_1H"),
            InlineKeyboardButton("4H", callback_data=f"opt_tf_{strategy}_4H"),
        ],
        _nav_row("menu_optimize"),
    ])


def optimize_range_menu(strategy: str, tf: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30d", callback_data=f"opt_run_{strategy}_{tf}_30d"),
            InlineKeyboardButton("60d", callback_data=f"opt_run_{strategy}_{tf}_60d"),
            InlineKeyboardButton("90d", callback_data=f"opt_run_{strategy}_{tf}_90d"),
        ],
        _nav_row(f"opt_strat_{strategy}"),
    ])


# ── Compare flow ──────────────────────────────────────────────────────────────────

def compare_a_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📐 Fibonacci",   callback_data="cmp_a_fib"),
            InlineKeyboardButton("🏦 Smart Money", callback_data="cmp_a_smc"),
        ],
        [
            InlineKeyboardButton("◆ Confluence",   callback_data="cmp_a_confluence"),
        ],
        _nav_row("menu_research"),
    ])


def compare_b_menu(strat_a: str) -> InlineKeyboardMarkup:
    all_strats = [("fib", "📐 Fibonacci"), ("smc", "🏦 Smart Money"), ("confluence", "◆ Confluence")]
    rows = []
    row  = []
    for sk, label in all_strats:
        if sk == strat_a:
            continue
        row.append(InlineKeyboardButton(label, callback_data=f"cmp_ab_{strat_a}_{sk}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append(_nav_row("menu_compare"))
    return InlineKeyboardMarkup(rows)


# ── Existing menus ────────────────────────────────────────────────────────────────

def alerts_menu(chat_id: int) -> InlineKeyboardMarkup:
    count = len(db.get_alerts(chat_id))
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▲ Alert Above",       callback_data="action_alert_above"),
            InlineKeyboardButton("▼ Alert Below",       callback_data="action_alert_below"),
        ],
        [
            InlineKeyboardButton(f"📋 My Alerts ({count})", callback_data="action_alert_list"),
            InlineKeyboardButton("🗑 Clear All",         callback_data="action_alert_clear"),
        ],
        _nav_row("menu_system"),
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
    rows.append(_nav_row("menu_system"))
    return InlineKeyboardMarkup(rows)


def summary_times_menu() -> InlineKeyboardMarkup:
    times = ["05:00", "07:00", "08:00", "10:00", "12:00", "16:00", "18:00", "20:00"]
    rows  = [
        [InlineKeyboardButton(f"🕐 {t} UTC", callback_data=f"action_summary_set_{t}") for t in times[i:i+2]]
        for i in range(0, len(times), 2)
    ]
    rows.append(_nav_row("menu_summary"))
    return InlineKeyboardMarkup(rows)


def settings_menu(chat_id: int) -> InlineKeyboardMarkup:
    sched       = db.get_summary_schedule(chat_id) or "Off"
    alert_count = len(db.get_alerts(chat_id))
    ai_mode     = db.get_ai_mode(chat_id)
    mode_label  = AI_MODE_LABELS.get(ai_mode, ai_mode)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 AI Mode: {mode_label}",  callback_data="menu_ai_mode")],
        [InlineKeyboardButton(f"📰 Summary: {sched} UTC",   callback_data="menu_summary")],
        [InlineKeyboardButton(f"🔔 Alerts: {alert_count}",  callback_data="menu_alerts")],
        [InlineKeyboardButton("🗑 Clear Conversation",       callback_data="action_clear")],
        _nav_row("menu_system"),
    ])


def ai_mode_menu(chat_id: int) -> InlineKeyboardMarkup:
    current = db.get_ai_mode(chat_id)
    rows    = []
    for mode, label in AI_MODE_LABELS.items():
        tick = " ✅" if mode == current else ""
        rows.append([InlineKeyboardButton(label + tick, callback_data=f"action_set_ai_mode_{mode}")])
    rows.append(_nav_row("menu_settings"))
    return InlineKeyboardMarkup(rows)


def fib_timeframe_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1H",    callback_data="fib_tf_1h"),
            InlineKeyboardButton("4H",    callback_data="fib_tf_4h"),
            InlineKeyboardButton("Daily", callback_data="fib_tf_daily"),
        ],
        _nav_row("menu_trading"),
    ])


def smc_timeframe_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1H",    callback_data="smc_tf_1h"),
            InlineKeyboardButton("4H",    callback_data="smc_tf_4h"),
            InlineKeyboardButton("Daily", callback_data="smc_tf_daily"),
        ],
        _nav_row("menu_trading"),
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
        [InlineKeyboardButton("🏠 Home",            callback_data="menu_main")],
    ])
