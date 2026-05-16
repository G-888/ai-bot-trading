"""
bot/handlers/decay_commands.py — Edge decay monitoring commands.

Handles: /decay, /edge, /regimehealth, /monitor, /stability
Python computes all metrics. AI only explains findings.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.menus import back_to_menu

logger = logging.getLogger(__name__)

VALID_STRATEGIES = {"fib", "fibonacci", "smc", "confluence"}


# ── /decay ───────────────────────────────────────────────────────────────────────

async def cmd_decay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Full edge deterioration report for one or all strategies.
    Usage: /decay [fib|smc|confluence]
    """
    args     = context.args or []
    strategy = args[0].lower().replace("fibonacci", "fib") if args else None

    if strategy and strategy not in VALID_STRATEGIES:
        await update.message.reply_text(
            f"Unknown strategy '{strategy}'.\nValid: fib, smc, confluence\n\n"
            "Usage: /decay [strategy]",
            reply_markup=back_to_menu(),
        )
        return

    target_label = strategy.upper() if strategy else "all strategies"
    status = await update.message.reply_text(
        f"Running edge decay analysis for {target_label}…\n"
        "Scanning 7d / 30d / 90d rolling windows…"
    )

    try:
        from analytics.decay import (
            run_decay_analysis,
            format_decay_report,
            generate_decay_chart,
        )

        decay = run_decay_analysis()

        if not decay:
            await status.edit_text(
                "No backtest data for decay analysis.\n\n"
                "Run backtests first:\n"
                "/backtest fib 1H 30d\n"
                "/backtest smc 1H 30d\n"
                "/backtest confluence 1H 30d",
                reply_markup=back_to_menu(),
            )
            return

        report_text = format_decay_report(decay, strategy=strategy)
        chart       = generate_decay_chart(
            {strategy: decay[strategy]} if strategy and strategy in decay else decay
        )

        await status.delete()

        await update.message.reply_photo(
            photo=chart,
            caption=f"Edge Decay Monitor — {target_label.upper()}",
            reply_markup=back_to_menu(),
        )

        chunk = 4000
        for i in range(0, len(report_text), chunk):
            await update.message.reply_text(
                report_text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(report_text) else None,
            )

    except Exception as e:
        logger.error("cmd_decay error: %s", e, exc_info=True)
        await status.edit_text(f"Decay analysis error: {e}")


# ── /edge ────────────────────────────────────────────────────────────────────────

async def cmd_edge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Compact edge health summary across all strategies.
    Usage: /edge
    """
    status = await update.message.reply_text("Computing edge health scores…")
    try:
        from analytics.decay import run_decay_analysis, format_edge_summary

        decay = run_decay_analysis()
        text  = format_edge_summary(decay)

        await status.delete()

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_edge error: %s", e, exc_info=True)
        await status.edit_text(f"Edge health error: {e}")


# ── /regimehealth ────────────────────────────────────────────────────────────────

async def cmd_regimehealth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Market regime dependency analysis with radar chart.
    Shows best/worst regime per strategy.
    Usage: /regimehealth
    """
    status = await update.message.reply_text("Analysing regime performance…")
    try:
        from analytics.performance import get_performance_stats
        from analytics.decay import run_decay_analysis, generate_regime_radar

        stats = get_performance_stats()
        decay = run_decay_analysis(stats)

        if not stats:
            await status.edit_text(
                "No regime data.\n\nRun backtests first:\n/backtest fib 1H 30d",
                reply_markup=back_to_menu(),
            )
            return

        radar = generate_regime_radar(decay)
        text  = _format_regime_health(stats)

        await status.delete()

        await update.message.reply_photo(
            photo=radar,
            caption="Regime Performance Radar",
            reply_markup=back_to_menu(),
        )

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_regimehealth error: %s", e, exc_info=True)
        await status.edit_text(f"Regime health error: {e}")


def _format_regime_health(stats: dict) -> str:
    lines = ["Market Regime Health Report", "=" * 32, ""]

    all_regimes = set()
    for s in stats.values():
        all_regimes.update(s.get("regime_stats", {}).keys())
    all_regimes = sorted(all_regimes)

    for strat_key, s in stats.items():
        regime_stats = s.get("regime_stats", {})
        if not regime_stats:
            continue

        viable = {r: rd for r, rd in regime_stats.items() if rd["trades"] >= 3}
        if not viable:
            continue

        best_regime  = max(viable, key=lambda r: viable[r]["win_rate"])
        worst_regime = min(viable, key=lambda r: viable[r]["win_rate"])
        spread = viable[best_regime]["win_rate"] - viable[worst_regime]["win_rate"]

        lines.append(f"[ {s['label']} ]")
        lines.append(f"  Best Regime:  {best_regime} ({viable[best_regime]['win_rate']:.0f}% WR)")
        lines.append(f"  Worst Regime: {worst_regime} ({viable[worst_regime]['win_rate']:.0f}% WR)")
        lines.append(f"  Spread:       {spread:.0f}pp")
        lines.append("")

        for regime in all_regimes:
            rd = regime_stats.get(regime)
            if not rd or rd["trades"] < 3:
                continue
            wr  = rd["win_rate"]
            bar = "█" * int(wr // 10) + "░" * (10 - int(wr // 10))
            flag = "  AVOID" if wr < 40 else ("  STRONG" if wr > 60 else "")
            lines.append(f"  {regime:<14} [{bar}] {wr:.0f}%  ({rd['trades']} trades){flag}")

        lines.append("")

    lines.append("Rankings by Regime Stability:")
    stability = []
    for strat_key, s in stats.items():
        regime_stats = s.get("regime_stats", {})
        viable = {r: rd for r, rd in regime_stats.items() if rd["trades"] >= 3}
        if not viable:
            continue
        wrs  = [rd["win_rate"] for rd in viable.values()]
        mean = sum(wrs) / len(wrs) if wrs else 0
        spread = (max(wrs) - min(wrs)) if len(wrs) > 1 else 0
        stability.append((s["label"], mean, spread, len(viable)))

    stability.sort(key=lambda x: x[2])
    for i, (label, mean, spread, n_regimes) in enumerate(stability):
        lines.append(f"  {i + 1}. {label:<14} avg={mean:.0f}% WR  spread={spread:.0f}pp  ({n_regimes} regimes)")

    return "\n".join(lines)


# ── /monitor ─────────────────────────────────────────────────────────────────────

async def cmd_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Show monitoring system status and trigger a manual snapshot.
    Usage: /monitor
    """
    status = await update.message.reply_text("Checking monitoring system status…")
    try:
        import storage.database as db
        from analytics.monitoring import (
            daily_performance_snapshot,
            daily_decay_check,
        )
        from analytics.performance import get_performance_stats

        await daily_performance_snapshot(context)
        stats   = get_performance_stats()
        snaps   = {}
        opt_runs = db.get_optimization_runs(limit=5)

        for strat_key in stats:
            latest = db.get_performance_snapshots(strat_key, limit=1)
            snaps[strat_key] = latest[0] if latest else None

        text = _format_monitor_status(stats, snaps, opt_runs)

        await status.delete()

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_monitor error: %s", e, exc_info=True)
        await status.edit_text(f"Monitor error: {e}")


def _format_monitor_status(
    stats: dict,
    snaps: dict,
    opt_runs: list[dict],
) -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "Monitoring System Status",
        "=" * 30,
        f"Last checked: {now}",
        "",
        "Scheduled Jobs:",
        "  Daily  02:00 — Performance snapshot",
        "  Daily  02:30 — Decay check + alerts",
        "  Hourly        — Drawdown spike check",
        "",
        "Strategy Snapshot Coverage:",
    ]

    for strat_key, s in stats.items():
        snap = snaps.get(strat_key)
        snap_date = snap["snapshot_date"] if snap else "No snapshots yet"
        snap_n    = snap.get("total_trades", 0) if snap else 0
        lines.append(f"  {s['label']:<16} Latest: {snap_date}  ({snap_n} trades)")

    lines.append("")
    lines.append("Recent Optimization Runs:")
    if opt_runs:
        for r in opt_runs[:5]:
            lines.append(
                f"  {r['strategy'].upper():<10} {r['timeframe']}  {r['lookback']}  "
                f"rob={r['robustness_score']:.0f}  ran={r['ran_at'][:10]}"
            )
    else:
        lines.append("  None — run /optimize fib 1H 30d")

    lines += [
        "",
        "Manual triggers:",
        "  /decay       — full decay report",
        "  /edge        — edge health summary",
        "  /regimehealth — regime analysis",
        "  /stability   — stability scores",
        "  /performance — performance dashboard",
        "  /leaderboard — strategy ranking",
        "  /diagnostics — health flags",
        "  /optimize    — parameter search",
    ]

    return "\n".join(lines)


# ── /stability ───────────────────────────────────────────────────────────────────

async def cmd_stability(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Strategy stability report — win rate consistency, PF stability, regime resilience.
    Usage: /stability
    """
    status = await update.message.reply_text("Computing stability scores…")
    try:
        from analytics.performance import get_performance_stats
        from analytics.leaderboard import build_leaderboard
        from analytics.decay import (
            run_decay_analysis,
            generate_confidence_calibration_chart,
        )

        stats  = get_performance_stats()
        ranked = build_leaderboard(stats)
        decay  = run_decay_analysis(stats)

        if not stats:
            await status.edit_text(
                "No data.\n\nRun /backtest first.",
                reply_markup=back_to_menu(),
            )
            return

        cal_chart = generate_confidence_calibration_chart(decay)
        text      = _format_stability_report(stats, ranked, decay)

        await status.delete()

        await update.message.reply_photo(
            photo=cal_chart,
            caption="Confidence Calibration Chart",
            reply_markup=back_to_menu(),
        )

        chunk = 4000
        for i in range(0, len(text), chunk):
            await update.message.reply_text(
                text[i:i + chunk],
                reply_markup=back_to_menu() if i + chunk >= len(text) else None,
            )

    except Exception as e:
        logger.error("cmd_stability error: %s", e, exc_info=True)
        await status.edit_text(f"Stability error: {e}")


def _format_stability_report(stats: dict, ranked: list[dict], decay: dict) -> str:
    lines = ["Strategy Stability Report", "=" * 30, ""]

    for entry in ranked:
        sk     = entry["strategy"]
        s      = stats.get(sk, {})
        d      = decay.get(sk, {})
        health = d.get("health", 0)

        wr30  = s.get("rolling_30d_wr", 0)
        wr90  = s.get("rolling_90d_wr", 0)
        wr_all = s.get("win_rate", 0)
        delta  = wr30 - wr90

        n_crit = sum(1 for i in d.get("issues", []) if i.get("severity") == "CRITICAL")
        n_warn = sum(1 for i in d.get("issues", []) if i.get("severity") == "WARNING")

        health_bar = "█" * (health // 10) + "░" * (10 - health // 10)
        cons_bar   = "█" * int(entry["score_consistency"] // 2.5) + "░" * (10 - int(entry["score_consistency"] // 2.5))

        lines.append(f"[ {entry['label']} ]")
        lines.append(f"  Edge Health:  [{health_bar}] {health}/100  {d.get('grade', '—')}")
        lines.append(f"  Consistency:  [{cons_bar}] {entry['score_consistency']:.1f}/25")
        lines.append(f"  Win Rates:    All={wr_all:.1f}%  90d={wr90:.1f}%  30d={wr30:.1f}%  ({delta:+.1f}pp)")
        lines.append(f"  PF:           {s.get('profit_factor', 0):.2f}")
        lines.append(f"  Sharpe:       {s.get('sharpe', 0):.2f}")
        lines.append(f"  Issues:       {n_crit} critical  {n_warn} warnings")

        if n_crit > 0 or n_warn > 0:
            top = [i for i in d.get("issues", []) if i.get("severity") in ("CRITICAL", "WARNING")][:2]
            for iss in top:
                icon = "✗" if iss["severity"] == "CRITICAL" else "!"
                lines.append(f"    {icon} {iss['msg']}")

        recs = d.get("recommendations", [])
        if recs:
            lines.append(f"  Action:  {recs[0]}")

        lines.append("")

    if ranked:
        lines.append("Stability Rankings:")
        stability_order = sorted(
            ranked,
            key=lambda r: -(r["score_consistency"] + r["score_drawdown"]),
        )
        for i, entry in enumerate(stability_order):
            d = decay.get(entry["strategy"], {})
            h = d.get("health", 0)
            lines.append(
                f"  {i + 1}. {entry['label']:<14}"
                f"  health={h}/100"
                f"  cons={entry['score_consistency']:.0f}"
                f"  dd={entry['score_drawdown']:.0f}"
            )

    return "\n".join(lines)
