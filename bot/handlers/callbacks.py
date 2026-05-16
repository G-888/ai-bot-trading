"""
bot/handlers/callbacks.py — Inline keyboard callback handler.

Routes all callback_data values to the appropriate action.
New flows: backtest (bt_*), performance hub (menu_performance),
optimize (opt_*), analytics actions (action_performance etc.)
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
    "XAUUSD Gold Assistant — Commands\n\n"
    "📈 /analyze       — Multi-TF AI signal\n"
    "📊 /chart         — 48h candlestick chart\n"
    "💰 /gold          — Live price + TF snapshot\n"
    "📐 /fibonacci     — Fibonacci analysis\n"
    "🏦 /smc           — Smart Money Concepts\n\n"
    "Research Platform\n"
    "/backtest fib 1H 30d   — Run backtest\n"
    "/performance           — Strategy dashboard\n"
    "/leaderboard           — Strategy ranking\n"
    "/diagnostics           — Health flags\n"
    "/compare fib smc       — Side-by-side\n"
    "/optimize fib 1H 30d   — Parameter search\n"
    "/decay [strategy]      — Decay monitor\n"
    "/edge                  — Edge health scores\n"
    "/regimehealth          — Regime analysis\n"
    "/stability             — Stability report\n"
    "/votes                 — Signal consensus\n"
    "/heatmap               — Signal heatmap\n\n"
    "🔔 Alerts\n"
    "/alert above 3250  — Alert above price\n"
    "/alert below 3200  — Alert below price\n"
    "/alerts            — List active alerts\n"
    "/clearalerts       — Remove all alerts\n\n"
    "📰 Daily Summary\n"
    "/summary 08:00   — Schedule daily recap\n"
    "/summaryoff      — Disable daily recap\n\n"
    "⚙️ Other\n"
    "/clear  — Reset conversation history\n"
    "/start  — Show main menu"
)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data    = query.data
    chat_id = query.message.chat_id

    # ── Main navigation ────────────────────────────────────────────────────────
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

    # ── Backtest flow ──────────────────────────────────────────────────────────
    elif data == "menu_backtest":
        await query.edit_message_text(
            "📊 Backtesting\n\nSelect strategy to backtest:",
            reply_markup=menus.backtest_strategy_menu(),
        )

    elif data.startswith("bt_strat_"):
        strategy = data.replace("bt_strat_", "")
        label = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"📊 Backtesting → {label}\n\nSelect timeframe:",
            reply_markup=menus.backtest_tf_menu(strategy),
        )

    elif data.startswith("bt_tf_"):
        # bt_tf_fib_1H
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"📊 Backtesting → {label} → {tf}\n\nSelect history range:",
            reply_markup=menus.backtest_range_menu(strategy, tf),
        )

    elif data.startswith("bt_run_"):
        # bt_run_fib_1H_30d
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        lookback = parts[4]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"📊 Backtesting → {label} → {tf} → {lookback}\n\n"
            "Running backtest — fetching data…"
        )
        await _run_backtest(query, chat_id, strategy, tf, lookback)

    # ── Performance research hub ───────────────────────────────────────────────
    elif data == "menu_performance":
        await query.edit_message_text(
            "🧠 Performance Research Hub\n\n"
            "Full institutional analytics and strategy evaluation:",
            reply_markup=menus.performance_menu(),
        )

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
        # opt_tf_fib_1H
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"⚙️ Optimization → {label} → {tf}\n\nSelect range:",
            reply_markup=menus.optimize_range_menu(strategy, tf),
        )

    elif data.startswith("opt_run_"):
        # opt_run_fib_1H_30d
        parts    = data.split("_")
        strategy = parts[2]
        tf       = parts[3]
        lookback = parts[4]
        label    = _STRAT_LABELS.get(strategy, strategy.title())
        await query.edit_message_text(
            f"⚙️ Optimization → {label} → {tf} → {lookback}\n\n"
            "Testing parameter grid — this takes 30-90 seconds…"
        )
        await _run_optimize(query, chat_id, strategy, tf, lookback)

    # ── Existing fast actions ──────────────────────────────────────────────────
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

    # ── Fibonacci timeframe selection ──────────────────────────────────────────
    elif data in ("action_fibonacci", "fib_back"):
        await query.edit_message_text(
            "📐 Fibonacci Analysis\n\nSelect timeframe:",
            reply_markup=menus.fib_timeframe_menu(),
        )

    elif data.startswith("fib_tf_"):
        tf = data.replace("fib_tf_", "")
        await query.edit_message_text(f"⏳ Running Fibonacci analysis ({tf.upper()})…")
        await _run_fibonacci(query, chat_id, tf)

    # ── SMC timeframe selection ────────────────────────────────────────────────
    elif data in ("action_smc", "smc_back"):
        await query.edit_message_text(
            "🏦 Smart Money Concepts\n\nSelect timeframe:",
            reply_markup=menus.smc_timeframe_menu(),
        )

    elif data.startswith("smc_tf_"):
        tf = data.replace("smc_tf_", "")
        await query.edit_message_text(f"⏳ Running SMC analysis ({tf.upper()})…")
        await _run_smc(query, chat_id, tf)

    # ── Heavy market actions ───────────────────────────────────────────────────
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
            await query.message.reply_photo(
                photo=buf, caption=caption,
                reply_markup=menus.back_to_menu(),
            )

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
                        InlineKeyboardButton("📈 Analyze", callback_data="action_analyze"),
                        InlineKeyboardButton("📊 Chart",   callback_data="action_chart"),
                    ],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")],
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


# ── Backtest runner ───────────────────────────────────────────────────────────────

async def _run_backtest(query, chat_id: int, strategy: str, tf: str, lookback: str) -> None:
    from bot.handlers.institutional_commands import _execute_backtest
    label = _STRAT_LABELS.get(strategy, strategy.title())
    breadcrumb = f"📊 Backtesting → {label} → {tf} → {lookback}"
    try:
        await _execute_backtest(
            message=query.message,
            strategy=strategy,
            timeframe=tf,
            lookback=lookback,
            breadcrumb=breadcrumb,
        )
    except Exception as e:
        logger.error("_run_backtest error: %s", e, exc_info=True)
        await query.message.reply_text(
            f"Backtest error: {e}\n\nTry: /backtest {strategy} {tf} {lookback}",
            reply_markup=menus.backtest_strategy_menu(),
        )


# ── Analytics runners ─────────────────────────────────────────────────────────────

async def _run_performance(query, chat_id: int) -> None:
    try:
        from analytics.performance import (
            get_performance_stats,
            format_performance_report,
            generate_performance_charts,
            generate_monthly_heatmap,
        )
        import storage.database as db_mod

        stats = get_performance_stats()
        if not stats:
            await query.message.reply_text(
                "No backtest data found.\n\n"
                "Run backtests first via 📊 Backtest in the main menu.",
                reply_markup=menus.performance_menu(),
            )
            return

        for strat_key, s in stats.items():
            db_mod.save_performance_snapshot(
                strategy=strat_key,
                win_rate=s["win_rate"],
                profit_factor=s["profit_factor"],
                expectancy=s["expectancy"],
                total_trades=s["total_trades"],
                vol_adj_score=s["vol_adj_score"],
            )

        perf_chart    = generate_performance_charts(stats)
        monthly_chart = generate_monthly_heatmap(stats)
        report_text   = format_performance_report(stats)

        await query.message.reply_photo(
            photo=perf_chart,
            caption="📈 Strategy Performance Dashboard",
            reply_markup=menus.refresh_and_menu("action_performance"),
        )
        await query.message.reply_photo(photo=monthly_chart, caption="Monthly PnL")

        chunk = 4000
        for i in range(0, len(report_text), chunk):
            is_last = i + chunk >= len(report_text)
            await query.message.reply_text(
                report_text[i:i + chunk],
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
        text   = format_leaderboard_text(ranked)
        chart  = generate_leaderboard_chart(ranked)

        await query.message.reply_photo(
            photo=chart,
            caption="🏆 Strategy Leaderboard",
            reply_markup=menus.refresh_and_menu("action_leaderboard"),
        )
        chunk = 4000
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await query.message.reply_text(
                text[i:i + chunk],
                reply_markup=menus.refresh_and_menu("action_leaderboard") if is_last else None,
            )

    except Exception as e:
        logger.error("_run_leaderboard error: %s", e, exc_info=True)
        await query.message.reply_text(f"Leaderboard error: {e}", reply_markup=menus.back_to_menu())


async def _run_diagnostics(query, chat_id: int) -> None:
    try:
        from analytics.performance import get_performance_stats
        from analytics.diagnostics import run_diagnostics, format_diagnostics_text

        stats      = get_performance_stats()
        all_issues = run_diagnostics(stats)
        text       = format_diagnostics_text(all_issues, stats)

        chunk = 4000
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await query.message.reply_text(
                text[i:i + chunk],
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
                "No decay data.\n\nRun backtests first via 📊 Backtest.",
                reply_markup=menus.performance_menu(),
            )
            return

        chart = generate_decay_chart(decay)
        text  = format_decay_report(decay)

        await query.message.reply_photo(
            photo=chart,
            caption="📉 Edge Decay Monitor",
            reply_markup=menus.refresh_and_menu("action_decay"),
        )
        chunk = 4000
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await query.message.reply_text(
                text[i:i + chunk],
                reply_markup=menus.refresh_and_menu("action_decay") if is_last else None,
            )

    except Exception as e:
        logger.error("_run_decay error: %s", e, exc_info=True)
        await query.message.reply_text(f"Decay error: {e}", reply_markup=menus.back_to_menu())


async def _run_edge(query, chat_id: int) -> None:
    try:
        from analytics.decay import run_decay_analysis, format_edge_summary

        decay = run_decay_analysis()
        text  = format_edge_summary(decay)
        chunk = 4000
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await query.message.reply_text(
                text[i:i + chunk],
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
        radar = generate_regime_radar(decay)
        text  = _format_regime_health(stats)

        await query.message.reply_photo(
            photo=radar,
            caption="🕸 Regime Performance Radar",
            reply_markup=menus.refresh_and_menu("action_regimehealth"),
        )
        chunk = 4000
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await query.message.reply_text(
                text[i:i + chunk],
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
                "No data.\n\nRun backtests first via 📊 Backtest.",
                reply_markup=menus.performance_menu(),
            )
            return

        cal_chart = generate_confidence_calibration_chart(decay)
        text      = _format_stability_report(stats, ranked, decay)

        await query.message.reply_photo(
            photo=cal_chart,
            caption="📊 Confidence Calibration",
            reply_markup=menus.refresh_and_menu("action_stability"),
        )
        chunk = 4000
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await query.message.reply_text(
                text[i:i + chunk],
                reply_markup=menus.refresh_and_menu("action_stability") if is_last else None,
            )

    except Exception as e:
        logger.error("_run_stability error: %s", e, exc_info=True)
        await query.message.reply_text(f"Stability error: {e}", reply_markup=menus.back_to_menu())


async def _run_optimize(query, chat_id: int, strategy: str, tf: str, lookback: str) -> None:
    try:
        from analytics.optimizer import run_optimization, format_optimizer_text

        result = run_optimization(strategy, tf, lookback)
        if "error" in result:
            await query.message.reply_text(
                f"Optimizer error: {result['error']}",
                reply_markup=menus.optimize_strategy_menu(),
            )
            return

        text = format_optimizer_text(result)
        chunk = 4000
        cb_key = f"opt_run_{strategy}_{tf}_{lookback}"
        for i in range(0, len(text), chunk):
            is_last = i + chunk >= len(text)
            await query.message.reply_text(
                text[i:i + chunk],
                reply_markup=menus.refresh_and_menu(cb_key) if is_last else None,
            )

    except Exception as e:
        logger.error("_run_optimize error: %s", e, exc_info=True)
        await query.message.reply_text(f"Optimize error: {e}", reply_markup=menus.back_to_menu())


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

    mode    = db.get_ai_mode(chat_id)
    prompt  = build_fib_prompt(fib, data, mode)
    ai_comment = generate_fib_commentary(prompt, mode)

    full_text = fib_text + "\n\n" + "─" * 28 + "\n\n" + ai_comment

    try:
        buf     = generate_fib_chart(df, fib, title=f"XAUUSD  •  Fibonacci ({tf.upper()})")
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

    data    = fetch_gold_data() or {"price": smc["price"]}
    mode    = db.get_ai_mode(chat_id)
    prompt  = build_smc_prompt(smc, data)
    ai_comment = generate_smc_commentary(prompt, mode)

    full_text = smc_text + "\n\n" + "─" * 28 + "\n\n" + ai_comment

    try:
        buf     = generate_smc_chart(df, smc, title=f"XAUUSD  •  Smart Money ({tf.upper()})")
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

    mode    = db.get_ai_mode(chat_id)
    prompt  = build_session_prompt(session_data, data)
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

    fib          = run_fibonacci_analysis(h1_df, lookback=4)
    smc          = run_smc_analysis(h1_df, lookback=3)
    session_data = analyze_session(h1_df, h4_df)

    result    = calculate_confluence(data, h1_df, smc_result=smc, fib_result=fib, session_data=session_data)
    conf_text = format_confluence_text(result)

    header = (
        f"Price: {data['price']}\n"
        f"Alignment: {data['alignment']}\n\n"
    )

    await query.message.reply_text(
        header + conf_text,
        reply_markup=menus.after_analysis_menu(),
    )
