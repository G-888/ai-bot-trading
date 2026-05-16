"""
bot/handlers/callbacks.py — Inline keyboard callback router.

4-section navigation: Trading | Analytics | Research | System
All institutional research flows routed here.
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

_STRAT_LABELS = {
    "fib":        "📐 Fibonacci",
    "smc":        "🏦 Smart Money",
    "confluence": "◆ Confluence",
}

_HELP_TEXT = (
    "┌─────────────────────────────────┐\n"
    "│  XAUUSD Gold AI — Command List  │\n"
    "└─────────────────────────────────┘\n\n"
    "📈 Trading\n"
    "/analyze      Multi-TF AI signal\n"
    "/chart        48h candlestick chart\n"
    "/gold         Live price + snapshot\n"
    "/fibonacci    Fibonacci analysis\n"
    "/smc          Smart Money Concepts\n"
    "/confluence   Signal confluence\n\n"
    "🧠 Analytics\n"
    "/backtest fib 1H 30d   Run backtest\n"
    "/performance           Strategy dashboard\n"
    "/leaderboard           Strategy ranking\n"
    "/diagnostics           Health flags\n"
    "/optimize fib 1H 30d   Parameter search\n"
    "/heatmap               Signal heatmap\n"
    "/votes                 Signal consensus\n\n"
    "📚 Research\n"
    "/decay [strat]    Decay monitor\n"
    "/edge             Edge health scores\n"
    "/regimehealth     Regime analysis\n"
    "/stability        Stability report\n"
    "/compare fib smc  Side-by-side\n"
    "/session [strat]  Session analytics\n"
    "/monitor          System status\n\n"
    "⚙️ System\n"
    "/alert above 3250   Set price alert\n"
    "/alerts             List active alerts\n"
    "/clearalerts        Remove all alerts\n"
    "/summary 08:00      Schedule summary\n"
    "/summaryoff         Disable summary\n"
    "/clear              Reset conversation\n"
    "/start              Show main menu"
)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    await query.answer()
    data    = query.data
    chat_id = query.message.chat_id

    # ── Top-level navigation ───────────────────────────────────────────────────
    if data == "menu_main":
        await query.edit_message_text(
            "┌──────────────────────────┐\n"
            "│  XAUUSD Gold AI Terminal │\n"
            "└──────────────────────────┘\n\n"
            "Select a section:",
            reply_markup=menus.main_menu(),
        )

    elif data == "menu_trading":
        await query.edit_message_text(
            "📈 Trading\n\nLive signals, charts, and strategy analysis:",
            reply_markup=menus.trading_menu(),
        )

    elif data == "menu_analytics":
        await query.edit_message_text(
            "🧠 Analytics\n\nBacktesting, performance, and diagnostics:",
            reply_markup=menus.analytics_menu(),
        )

    elif data == "menu_research":
        await query.edit_message_text(
            "📚 Research\n\nEdge analysis, regime health, and strategy comparison:",
            reply_markup=menus.research_menu(),
        )

    elif data == "menu_system":
        await query.edit_message_text(
            "⚙️ System\n\nAlerts, summaries, AI mode, and settings:",
            reply_markup=menus.system_menu(chat_id),
        )

    # ── Settings / system navigation ──────────────────────────────────────────
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

    # ── Backtest flow ──────────────────────────────────────────────────────────
    elif data == "menu_backtest":
        await query.edit_message_text(
            "📊 Backtesting\n\nSelect strategy:",
            reply_markup=menus.backtest_strategy_menu(),
        )

    elif data.startswith("bt_strat_"):
        strategy = data.replace("bt_strat_", "")
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"📊 Backtesting → {label}\n\nSelect timeframe:",
            reply_markup=menus.backtest_tf_menu(strategy),
        )

    elif data.startswith("bt_tf_"):
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"📊 Backtesting → {label} → {tf}\n\nSelect history range:",
            reply_markup=menus.backtest_range_menu(strategy, tf),
        )

    elif data.startswith("bt_run_"):
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        lookback = parts[4]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"📊 Backtesting → {label} → {tf} → {lookback}\n\nFetching data…"
        )
        await _run_backtest(query, chat_id, strategy, tf, lookback)

    # ── Optimize flow ──────────────────────────────────────────────────────────
    elif data == "menu_optimize":
        await query.edit_message_text(
            "⚙️ Optimization → Select strategy:",
            reply_markup=menus.optimize_strategy_menu(),
        )

    elif data.startswith("opt_strat_"):
        strategy = data.replace("opt_strat_", "")
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"⚙️ Optimization → {label}\n\nSelect timeframe:",
            reply_markup=menus.optimize_tf_menu(strategy),
        )

    elif data.startswith("opt_tf_"):
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"⚙️ Optimization → {label} → {tf}\n\nSelect range:",
            reply_markup=menus.optimize_range_menu(strategy, tf),
        )

    elif data.startswith("opt_run_"):
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        lookback = parts[4]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"⚙️ Optimization → {label} → {tf} → {lookback}\n\n"
            "Testing parameter grid — 30-90 seconds…"
        )
        await _run_optimize(query, chat_id, strategy, tf, lookback)

    # ── Compare flow ───────────────────────────────────────────────────────────
    elif data == "menu_compare":
        await query.edit_message_text(
            "⚖️ Strategy Comparison\n\nSelect first strategy:",
            reply_markup=menus.compare_a_menu(),
        )

    elif data.startswith("cmp_a_"):
        strat_a = data.replace("cmp_a_", "")
        label_a = _STRAT_LABELS.get(strat_a, strat_a.title())
        await query.edit_message_text(
            f"⚖️ Compare: {label_a} vs…\n\nSelect second strategy:",
            reply_markup=menus.compare_b_menu(strat_a),
        )

    elif data.startswith("cmp_ab_"):
        parts   = data.split("_")
        strat_a = parts[2]
        strat_b = parts[3]
        label_a = _STRAT_LABELS.get(strat_a, strat_a.title())
        label_b = _STRAT_LABELS.get(strat_b, strat_b.title())
        await query.edit_message_text(
            f"⚖️ Comparing {label_a} vs {label_b}…"
        )
        await _run_compare(query, chat_id, strat_a, strat_b)

    # ── Analytics actions ──────────────────────────────────────────────────────
    elif data == "action_performance":
        await query.edit_message_text("🧠 Compiling performance report…")
        await _run_performance(query, chat_id)

    elif data == "action_leaderboard":
        await query.edit_message_text("🏆 Building strategy leaderboard…")
        await _run_leaderboard(query, chat_id)

    elif data == "action_diagnostics":
        await query.edit_message_text("🩺 Running strategy diagnostics…")
        await _run_diagnostics(query, chat_id)

    elif data == "action_heatmap":
        await query.edit_message_text("🌡 Generating signal heatmap…")
        await _run_heatmap(query, chat_id)

    elif data == "action_votes":
        await query.edit_message_text("🗳 Computing signal consensus…")
        await _run_votes(query, chat_id)

    elif data == "action_decay":
        await query.edit_message_text("📉 Running edge decay analysis…")
        await _run_decay(query, chat_id)

    elif data == "action_edge":
        await query.edit_message_text("🔬 Computing edge health scores…")
        await _run_edge(query, chat_id)

    elif data == "action_regimehealth":
        await query.edit_message_text("🕸 Analysing regime performance…")
        await _run_regimehealth(query, chat_id)

    elif data == "action_stability":
        await query.edit_message_text("📊 Computing stability scores…")
        await _run_stability(query, chat_id)

    elif data == "action_session_analytics":
        await query.edit_message_text("🕐 Analysing session performance…")
        await _run_session_analytics(query, chat_id)

    elif data == "action_weekly":
        await query.edit_message_text("📋 Generating weekly research report…")
        await _run_weekly_report(query, chat_id)

    elif data == "action_monitor":
        await query.edit_message_text("📡 Checking monitoring system…")
        await _run_monitor(query, chat_id)

    # ── Fast actions ───────────────────────────────────────────────────────────
    elif data == "action_help":
        await query.edit_message_text(_HELP_TEXT, reply_markup=menus.back_to_menu())

    elif data == "action_clear":
        conversation_history.pop(chat_id, None)
        await query.edit_message_text("Conversation cleared.", reply_markup=menus.back_to_menu())

    elif data.startswith("action_set_ai_mode_"):
        mode  = data.replace("action_set_ai_mode_", "")
        db.set_ai_mode(chat_id, mode)
        label = menus.AI_MODE_LABELS.get(mode, mode)
        await query.edit_message_text(
            f"AI mode set to {label}.\n\nAll future analyses will use this persona.",
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
                lines.append(f"{arrow} {a['direction'].capitalize()} {a['price']}  (#{a['id']})")
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

    # ── Fibonacci TF selection ─────────────────────────────────────────────────
    elif data in ("action_fibonacci", "fib_back"):
        await query.edit_message_text(
            "📐 Trading → Fibonacci\n\nSelect timeframe:",
            reply_markup=menus.fib_timeframe_menu(),
        )

    elif data.startswith("fib_tf_"):
        tf = data.replace("fib_tf_", "")
        await query.edit_message_text(f"📐 Trading → Fibonacci → {tf.upper()}\n\n⏳ Running…")
        await _run_fibonacci(query, chat_id, tf)

    # ── SMC TF selection ───────────────────────────────────────────────────────
    elif data in ("action_smc", "smc_back"):
        await query.edit_message_text(
            "🏦 Trading → Smart Money\n\nSelect timeframe:",
            reply_markup=menus.smc_timeframe_menu(),
        )

    elif data.startswith("smc_tf_"):
        tf = data.replace("smc_tf_", "")
        await query.edit_message_text(f"🏦 Trading → Smart Money → {tf.upper()}\n\n⏳ Running…")
        await _run_smc(query, chat_id, tf)

    # ── Market actions ─────────────────────────────────────────────────────────
    elif data == "action_analyze":
        await query.edit_message_text("📈 Trading → Analyze\n\n⏳ Fetching live XAUUSD data…")
        reply = await _core_analyze(chat_id)
        await query.message.reply_text(reply, reply_markup=menus.after_analysis_menu())

    elif data == "action_chart":
        await query.edit_message_text("📈 Trading → Chart\n\n⏳ Generating chart…")
        buf, caption = await _core_chart()
        if buf is None:
            await query.message.reply_text(caption, reply_markup=menus.back_to_menu())
        else:
            await query.message.reply_photo(photo=buf, caption=caption,
                                             reply_markup=menus.back_to_menu())

    elif data == "action_price":
        await query.edit_message_text("💰 Fetching live price…")
        data_live = fetch_gold_data()
        if not data_live:
            await query.message.reply_text("Could not fetch price.", reply_markup=menus.back_to_menu())
        else:
            await query.message.reply_text(
                f"┌────────────────────────┐\n"
                f"│  XAUUSD  Live Price    │\n"
                f"├────────────────────────┤\n"
                f"│ Price: {data_live['price']}\n"
                f"│ 1H:    {data_live['h1_bias']}  ({data_live['h1_pct']:+.2f}%)\n"
                f"│ 4H:    {data_live['h4_trend']}  ({data_live['h4_pct']:+.2f}%)\n"
                f"│ Daily: {data_live['d1_momentum']}\n"
                f"│ Align: {data_live['alignment']}\n"
                f"│ S: {data_live['h1_support']}  R: {data_live['h1_resistance']}\n"
                f"└────────────────────────┘",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("📊 Analyze", callback_data="action_analyze"),
                        InlineKeyboardButton("📈 Chart",   callback_data="action_chart"),
                    ],
                    [InlineKeyboardButton("🏠 Home", callback_data="menu_main")],
                ]),
            )

    elif data == "action_sessions":
        await query.edit_message_text("🕐 Trading → Sessions\n\n⏳ Analyzing sessions…")
        await _run_sessions(query, chat_id)

    elif data == "action_confluence":
        await query.edit_message_text("◆ Trading → Confluence\n\n⏳ Computing confluence…")
        await _run_confluence(query, chat_id)

    elif data == "action_summary_now":
        await query.edit_message_text("📰 Generating summary…")
        data_live = fetch_gold_data()
        if not data_live:
            await query.message.reply_text("Could not fetch data.", reply_markup=menus.back_to_menu())
        else:
            sched_time = db.get_summary_schedule(chat_id) or "now"
            msg = _build_summary_message(data_live, sched_time)
            await query.message.reply_text(msg, reply_markup=menus.back_to_menu())


# ── Backtest runner ───────────────────────────────────────────────────────────────

async def _run_backtest(query, chat_id: int, strategy: str, tf: str, lookback: str) -> None:
    from bot.handlers.institutional_commands import _execute_backtest
    label      = _STRAT_LABELS.get(strategy, strategy.title())
    breadcrumb = f"📊 Backtesting → {label} → {tf} → {lookback}"
    try:
        await _execute_backtest(query.message, strategy, tf, lookback, breadcrumb)
    except Exception as e:
        logger.error("_run_backtest error: %s", e, exc_info=True)
        await query.message.reply_text(
            f"Backtest error: {e}",
            reply_markup=menus.backtest_strategy_menu(),
        )


# ── Analytics runners ─────────────────────────────────────────────────────────────

async def _run_performance(query, chat_id: int) -> None:
    try:
        from analytics.performance import (
            get_performance_stats, format_performance_report,
            generate_performance_charts, generate_monthly_heatmap,
        )
        import storage.database as db_mod

        stats = get_performance_stats()
        if not stats:
            await query.message.reply_text(
                "No backtest data.\n\nUse 🧠 Analytics → 📊 Backtest to run backtests.",
                reply_markup=menus.analytics_menu(),
            )
            return

        for sk, s in stats.items():
            db_mod.save_performance_snapshot(sk, s["win_rate"], s["profit_factor"],
                                              s["expectancy"], s["total_trades"], s["vol_adj_score"])

        await query.message.reply_photo(
            photo=generate_performance_charts(stats),
            caption="📈 Strategy Performance Dashboard",
            reply_markup=menus.refresh_and_menu("action_performance", "menu_analytics"),
        )
        await query.message.reply_photo(photo=generate_monthly_heatmap(stats),
                                         caption="Monthly PnL")
        text = format_performance_report(stats)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_performance") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_performance error: %s", e, exc_info=True)
        await query.message.reply_text(f"Performance error: {e}", reply_markup=menus.back_to_menu())


async def _run_leaderboard(query, chat_id: int) -> None:
    try:
        from analytics.performance import get_performance_stats
        from analytics.leaderboard import build_leaderboard, format_leaderboard_text, generate_leaderboard_chart

        stats  = get_performance_stats()
        ranked = build_leaderboard(stats)
        await query.message.reply_photo(
            photo=generate_leaderboard_chart(ranked),
            caption="🏆 Strategy Leaderboard",
            reply_markup=menus.refresh_and_menu("action_leaderboard", "menu_analytics"),
        )
        text = format_leaderboard_text(ranked)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_leaderboard") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_leaderboard error: %s", e, exc_info=True)
        await query.message.reply_text(f"Leaderboard error: {e}", reply_markup=menus.back_to_menu())


async def _run_diagnostics(query, chat_id: int) -> None:
    try:
        from analytics.performance import get_performance_stats
        from analytics.diagnostics import run_diagnostics, format_diagnostics_text

        stats = get_performance_stats()
        text  = format_diagnostics_text(run_diagnostics(stats), stats)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_diagnostics") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_diagnostics error: %s", e, exc_info=True)
        await query.message.reply_text(f"Diagnostics error: {e}", reply_markup=menus.back_to_menu())


async def _run_heatmap(query, chat_id: int) -> None:
    try:
        from bot.handlers.institutional_commands import _execute_heatmap
        await _execute_heatmap(query.message)
    except Exception as e:
        logger.error("_run_heatmap error: %s", e, exc_info=True)
        await query.message.reply_text(f"Heatmap error: {e}", reply_markup=menus.back_to_menu())


async def _run_votes(query, chat_id: int) -> None:
    try:
        from bot.handlers.institutional_commands import _execute_votes
        await _execute_votes(query.message)
    except Exception as e:
        logger.error("_run_votes error: %s", e, exc_info=True)
        await query.message.reply_text(f"Votes error: {e}", reply_markup=menus.back_to_menu())


async def _run_decay(query, chat_id: int) -> None:
    try:
        from analytics.decay import run_decay_analysis, format_decay_report, generate_decay_chart

        decay = run_decay_analysis()
        if not decay:
            await query.message.reply_text(
                "No decay data.\n\nRun backtests first.", reply_markup=menus.analytics_menu(),
            )
            return

        await query.message.reply_photo(
            photo=generate_decay_chart(decay),
            caption="📉 Edge Decay Monitor",
            reply_markup=menus.refresh_and_menu("action_decay", "menu_analytics"),
        )
        text = format_decay_report(decay)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_decay") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_decay error: %s", e, exc_info=True)
        await query.message.reply_text(f"Decay error: {e}", reply_markup=menus.back_to_menu())


async def _run_edge(query, chat_id: int) -> None:
    try:
        from analytics.decay import run_decay_analysis, format_edge_summary

        text = format_edge_summary(run_decay_analysis())
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_edge") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_edge error: %s", e, exc_info=True)
        await query.message.reply_text(f"Edge error: {e}", reply_markup=menus.back_to_menu())


async def _run_regimehealth(query, chat_id: int) -> None:
    try:
        from analytics.performance import get_performance_stats
        from analytics.decay import run_decay_analysis, generate_regime_radar
        from bot.handlers.decay_commands import _format_regime_health

        stats = get_performance_stats()
        decay = run_decay_analysis(stats)

        await query.message.reply_photo(
            photo=generate_regime_radar(decay),
            caption="🕸 Regime Performance Radar",
            reply_markup=menus.refresh_and_menu("action_regimehealth", "menu_research"),
        )
        text = _format_regime_health(stats)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_regimehealth") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_regimehealth error: %s", e, exc_info=True)
        await query.message.reply_text(f"Regime health error: {e}", reply_markup=menus.back_to_menu())


async def _run_stability(query, chat_id: int) -> None:
    try:
        from analytics.performance import get_performance_stats
        from analytics.leaderboard import build_leaderboard
        from analytics.decay import run_decay_analysis, generate_confidence_calibration_chart
        from bot.handlers.decay_commands import _format_stability_report

        stats  = get_performance_stats()
        ranked = build_leaderboard(stats)
        decay  = run_decay_analysis(stats)

        if not stats:
            await query.message.reply_text(
                "No data.\n\nRun backtests first.", reply_markup=menus.research_menu(),
            )
            return

        await query.message.reply_photo(
            photo=generate_confidence_calibration_chart(decay),
            caption="📊 Confidence Calibration",
            reply_markup=menus.refresh_and_menu("action_stability", "menu_research"),
        )
        text = _format_stability_report(stats, ranked, decay)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_stability") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_stability error: %s", e, exc_info=True)
        await query.message.reply_text(f"Stability error: {e}", reply_markup=menus.back_to_menu())


async def _run_session_analytics(query, chat_id: int) -> None:
    try:
        from analytics.session_analytics import (
            run_session_analysis, format_session_report, generate_session_chart,
        )

        analysis = run_session_analysis()
        if not analysis:
            await query.message.reply_text(
                "No session data.\n\nRun backtests first.", reply_markup=menus.analytics_menu(),
            )
            return

        await query.message.reply_photo(
            photo=generate_session_chart(analysis),
            caption="🕐 Session Performance Analytics",
            reply_markup=menus.refresh_and_menu("action_session_analytics", "menu_analytics"),
        )
        text = format_session_report(analysis)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_session_analytics") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_session_analytics error: %s", e, exc_info=True)
        await query.message.reply_text(f"Session analytics error: {e}", reply_markup=menus.back_to_menu())


async def _run_compare(query, chat_id: int, strat_a: str, strat_b: str) -> None:
    try:
        from analytics.performance import get_performance_stats, generate_performance_charts
        from bot.handlers.analytics_commands import _format_comparison

        stats  = get_performance_stats()
        subset = {k: v for k, v in stats.items() if k in (strat_a, strat_b)}

        if len(subset) < 2:
            missing = [x for x in (strat_a, strat_b) if x not in stats]
            await query.message.reply_text(
                f"No data for: {', '.join(m.upper() for m in missing)}\n\n"
                + "\n".join(f"/backtest {m} 1H 30d" for m in missing),
                reply_markup=menus.research_menu(),
            )
            return

        label_a = _STRAT_LABELS.get(strat_a, strat_a.title())
        label_b = _STRAT_LABELS.get(strat_b, strat_b.title())

        await query.message.reply_photo(
            photo=generate_performance_charts(subset),
            caption=f"⚖️ {label_a} vs {label_b}",
            reply_markup=menus.refresh_and_menu(f"cmp_ab_{strat_a}_{strat_b}", "menu_compare"),
        )
        text = _format_comparison(subset, strat_a, strat_b, stats)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu(f"cmp_ab_{strat_a}_{strat_b}") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_compare error: %s", e, exc_info=True)
        await query.message.reply_text(f"Compare error: {e}", reply_markup=menus.back_to_menu())


async def _run_optimize(query, chat_id: int, strategy: str, tf: str, lookback: str) -> None:
    try:
        from analytics.optimizer import run_optimization, format_optimizer_text

        result = run_optimization(strategy, tf, lookback)
        if "error" in result:
            await query.message.reply_text(f"Optimizer error: {result['error']}",
                                            reply_markup=menus.optimize_strategy_menu())
            return

        text   = format_optimizer_text(result)
        cb_key = f"opt_run_{strategy}_{tf}_{lookback}"
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu(cb_key) if is_last else None,
            )
    except Exception as e:
        logger.error("_run_optimize error: %s", e, exc_info=True)
        await query.message.reply_text(f"Optimize error: {e}", reply_markup=menus.back_to_menu())


async def _run_weekly_report(query, chat_id: int) -> None:
    try:
        from analytics.performance import get_performance_stats, format_performance_report
        from analytics.decay import run_decay_analysis, format_edge_summary
        from analytics.leaderboard import build_leaderboard

        stats  = get_performance_stats()
        decay  = run_decay_analysis(stats)
        ranked = build_leaderboard(stats)

        if not stats:
            await query.message.reply_text(
                "No data for weekly report.\n\nRun backtests first.",
                reply_markup=menus.research_menu(),
            )
            return

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        lines = [
            f"┌────────────────────────────────┐",
            f"│  WEEKLY RESEARCH REPORT        │",
            f"│  {now}                   │",
            f"└────────────────────────────────┘",
            "",
            "═══ EDGE HEALTH SUMMARY ═══",
        ]
        lines.append(format_edge_summary(decay))
        lines.append("═══ STRATEGY RANKING ═══")

        for i, r in enumerate(ranked[:3]):
            d     = decay.get(r["strategy"], {})
            health = d.get("health", 0)
            lines.append(
                f"  {i+1}. {r['label']:<14} "
                f"score={r['total_score']:.0f}  health={health}/100  WR={r['win_rate']:.1f}%"
            )

        lines.append("")
        lines.append("═══ KEY WARNINGS ═══")
        any_warn = False
        for strat_key, d in decay.items():
            crits = [i for i in d.get("issues", []) if i.get("severity") == "CRITICAL"]
            for issue in crits[:2]:
                lines.append(f"  ✗ {d['label']}: {issue['msg']}")
                any_warn = True
        if not any_warn:
            lines.append("  No critical issues detected.")

        text = "\n".join(lines)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_weekly", "menu_research") if is_last else None,
            )

    except Exception as e:
        logger.error("_run_weekly_report error: %s", e, exc_info=True)
        await query.message.reply_text(f"Weekly report error: {e}", reply_markup=menus.back_to_menu())


async def _run_monitor(query, chat_id: int) -> None:
    try:
        from bot.handlers.decay_commands import _format_monitor_status
        import storage.database as db_mod
        from analytics.performance import get_performance_stats

        stats    = get_performance_stats()
        snaps    = {sk: (db_mod.get_performance_snapshots(sk, limit=1) or [None])[0]
                    for sk in stats}
        opt_runs = db_mod.get_optimization_runs(limit=5)

        text = _format_monitor_status(stats, snaps, opt_runs)
        for i in range(0, len(text), 4000):
            is_last = i + 4000 >= len(text)
            await query.message.reply_text(
                text[i:i + 4000],
                reply_markup=menus.refresh_and_menu("action_monitor", "menu_research") if is_last else None,
            )
    except Exception as e:
        logger.error("_run_monitor error: %s", e, exc_info=True)
        await query.message.reply_text(f"Monitor error: {e}", reply_markup=menus.back_to_menu())


# ── Strategy runners (unchanged logic) ───────────────────────────────────────────

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
            f"Insufficient data for {tf.upper()} Fibonacci.", reply_markup=menus.back_to_menu(),
        )
        return

    fib = run_fibonacci_analysis(df, lookback=4 if tf == "1h" else 5)
    if fib is None:
        await query.message.reply_text(
            "No clear swing detected. Try a different timeframe.",
            reply_markup=menus.fib_timeframe_menu(),
        )
        return

    data     = fetch_gold_data() or {"price": float(df["Close"].iloc[-1]), "alignment": "N/A"}
    mode     = db.get_ai_mode(chat_id)
    prompt   = build_fib_prompt(fib, data, mode)
    ai_cmnt  = generate_fib_commentary(prompt, mode)
    full_txt = format_fib_text(fib) + "\n\n" + "─" * 28 + "\n\n" + ai_cmnt

    try:
        buf = generate_fib_chart(df, fib, title=f"XAUUSD  •  Fibonacci ({tf.upper()})")
        await query.message.reply_photo(
            photo=buf,
            caption=f"Fibonacci ({tf.upper()}) • Confluence: {fib['confluence_score']:.0f}%",
            reply_markup=menus.back_to_menu(),
        )
        await query.message.reply_text(full_txt, reply_markup=menus.back_to_menu())
    except Exception as e:
        logger.error("Fib chart error: %s", e)
        await query.message.reply_text(full_txt, reply_markup=menus.back_to_menu())


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
            f"Insufficient data for {tf.upper()} SMC.", reply_markup=menus.back_to_menu(),
        )
        return

    smc      = run_smc_analysis(df, lookback=3 if tf == "1h" else 4)
    data     = fetch_gold_data() or {"price": smc["price"]}
    mode     = db.get_ai_mode(chat_id)
    prompt   = build_smc_prompt(smc, data)
    ai_cmnt  = generate_smc_commentary(prompt, mode)
    full_txt = format_smc_text(smc) + "\n\n" + "─" * 28 + "\n\n" + ai_cmnt

    try:
        buf = generate_smc_chart(df, smc, title=f"XAUUSD  •  Smart Money ({tf.upper()})")
        await query.message.reply_photo(
            photo=buf, caption=f"Smart Money Concepts ({tf.upper()})",
            reply_markup=menus.back_to_menu(),
        )
        await query.message.reply_text(full_txt, reply_markup=menus.back_to_menu())
    except Exception as e:
        logger.error("SMC chart error: %s", e)
        await query.message.reply_text(full_txt, reply_markup=menus.back_to_menu())


async def _run_sessions(query, chat_id: int) -> None:
    from strategies.session import analyze_session
    from ai.ai_router import generate_session_commentary
    from ai.prompts import build_session_prompt

    data = fetch_gold_data()
    if not data:
        await query.message.reply_text("Could not fetch data.", reply_markup=menus.back_to_menu())
        return

    session_data = analyze_session(data["h1_df"], data["h4_df"])
    ranges       = session_data.get("session_ranges", {})
    range_lines  = [
        f"  {sess:12s} {r['low']} – {r['high']}  (range: {r['range']})"
        if r.get("range") is not None else f"  {sess:12s} N/A"
        for sess, r in ranges.items()
    ]

    session_text = (
        "┌─────────────────────────────┐\n"
        "│  SESSION INTELLIGENCE       │\n"
        "├─────────────────────────────┤\n"
        f"│ Current: {session_data['current_session']}\n"
        f"│ Bias:    {session_data['session_bias']}\n"
        f"│ Volat:   {session_data['volatility']}\n"
        f"│ Pattern: {session_data['pattern']}\n"
        f"│ Cont %:  {session_data['continuation_pct']:.0f}%\n"
        "├─────────────────────────────┤\n"
        + "\n".join(range_lines) + "\n"
        "└─────────────────────────────┘\n\n"
        f"Note: {session_data['bias_note']}"
    )

    mode     = db.get_ai_mode(chat_id)
    prompt   = build_session_prompt(session_data, data)
    ai_cmnt  = generate_session_commentary(prompt, mode)
    full_txt = session_text + "\n\n" + "─" * 28 + "\n\n" + ai_cmnt

    await query.message.reply_text(full_txt, reply_markup=menus.back_to_menu())


async def _run_confluence(query, chat_id: int) -> None:
    from signals.confluence import calculate_confluence, format_confluence_text
    from strategies.fibonacci import run_fibonacci_analysis
    from strategies.smc import run_smc_analysis
    from strategies.session import analyze_session

    data = fetch_gold_data()
    if not data:
        await query.message.reply_text("Could not fetch data.", reply_markup=menus.back_to_menu())
        return

    h1_df        = data["h1_df"]
    fib          = run_fibonacci_analysis(h1_df, lookback=4)
    smc          = run_smc_analysis(h1_df, lookback=3)
    session_data = analyze_session(h1_df, data["h4_df"])
    result       = calculate_confluence(data, h1_df, smc_result=smc,
                                        fib_result=fib, session_data=session_data)
    conf_text    = format_confluence_text(result)

    await query.message.reply_text(
        f"Price: {data['price']}\nAlignment: {data['alignment']}\n\n" + conf_text,
        reply_markup=menus.after_analysis_menu(),
    )
