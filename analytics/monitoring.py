"""
analytics/monitoring.py — Continuous edge monitoring scheduler.

Runs daily jobs:
  - snapshot current performance metrics
  - compute decay scores
  - update regime statistics
  - check alert thresholds → dispatch Telegram alerts

Integrated with APScheduler via main.py job_queue.
"""
import logging
from datetime import datetime, timezone

import storage.database as db

logger = logging.getLogger(__name__)

ALERT_THRESHOLDS = {
    "edge_health_warn":     65,
    "edge_health_critical": 40,
    "wr_drop_warn":         -8.0,
    "wr_drop_critical":     -18.0,
    "dd_spike_pct":         50.0,
}

_last_known_health: dict[str, int] = {}


async def daily_performance_snapshot(context) -> None:
    """
    APScheduler job — runs once per day.
    Takes a performance snapshot for all strategies and saves to DB.
    """
    logger.info("[monitor] Running daily performance snapshot…")
    try:
        from analytics.performance import get_performance_stats
        stats = get_performance_stats()

        for strat_key, s in stats.items():
            db.save_performance_snapshot(
                strategy=strat_key,
                win_rate=s["win_rate"],
                profit_factor=s["profit_factor"],
                expectancy=s["expectancy"],
                total_trades=s["total_trades"],
                vol_adj_score=s["vol_adj_score"],
            )
            for regime, rd in s.get("regime_stats", {}).items():
                db.upsert_regime_statistics(
                    strategy=strat_key,
                    regime=regime,
                    trades=rd["trades"],
                    win_rate=rd["win_rate"],
                    total_pnl=rd["total_pnl"],
                )

        logger.info("[monitor] Snapshot saved for %d strategies.", len(stats))

    except Exception as e:
        logger.error("[monitor] Snapshot error: %s", e, exc_info=True)


async def daily_decay_check(context) -> None:
    """
    APScheduler job — runs once per day.
    Runs decay analysis and fires Telegram alerts when thresholds crossed.
    """
    logger.info("[monitor] Running daily decay check…")
    try:
        from analytics.decay import run_decay_analysis
        from analytics.alerts import dispatch_edge_alert

        decay = run_decay_analysis()

        for strat_key, d in decay.items():
            health = d["health"]
            prev   = _last_known_health.get(strat_key)

            should_alert = False
            alert_type   = None

            if health <= ALERT_THRESHOLDS["edge_health_critical"]:
                if prev is None or prev > ALERT_THRESHOLDS["edge_health_critical"]:
                    should_alert = True
                    alert_type   = "CRITICAL"

            elif health <= ALERT_THRESHOLDS["edge_health_warn"]:
                if prev is None or prev > ALERT_THRESHOLDS["edge_health_warn"]:
                    should_alert = True
                    alert_type   = "WARNING"

            if should_alert and alert_type:
                await dispatch_edge_alert(
                    context=context,
                    strategy=strat_key,
                    label=d["label"],
                    health_now=health,
                    health_prev=prev,
                    alert_type=alert_type,
                    issues=d.get("issues", []),
                    recommendations=d.get("recommendations", []),
                )

            _last_known_health[strat_key] = health

        logger.info("[monitor] Decay check complete for %d strategies.", len(decay))

    except Exception as e:
        logger.error("[monitor] Decay check error: %s", e, exc_info=True)


async def hourly_drawdown_check(context) -> None:
    """
    APScheduler job — runs hourly.
    Fires alert if recent drawdown spikes beyond historical baseline.
    """
    logger.info("[monitor] Running hourly drawdown check…")
    try:
        from analytics.performance import get_performance_stats, _get_all_trades
        from analytics.alerts import dispatch_drawdown_alert

        all_trades = _get_all_trades()
        stats      = get_performance_stats()

        for strat_key, s in stats.items():
            m30_dd = s.get("max_drawdown", 0)
            snaps  = db.get_performance_snapshots(strat_key, limit=30)
            if not snaps or len(snaps) < 3:
                continue
            hist_dd = sum(snap.get("vol_adj_score", 0) for snap in snaps) / len(snaps)
            if hist_dd <= 0:
                continue
            if m30_dd > hist_dd * (1 + ALERT_THRESHOLDS["dd_spike_pct"] / 100):
                await dispatch_drawdown_alert(
                    context=context,
                    strategy=strat_key,
                    label=s["label"],
                    dd_now=m30_dd,
                    dd_baseline=hist_dd,
                )

    except Exception as e:
        logger.error("[monitor] Drawdown check error: %s", e, exc_info=True)


def register_monitoring_jobs(app) -> None:
    """
    Register all monitoring jobs onto the APScheduler job_queue.
    Call this from main.py after app is built.
    """
    jq = app.job_queue

    jq.run_daily(daily_performance_snapshot, time=datetime.strptime("02:00", "%H:%M").time())
    jq.run_daily(daily_decay_check,          time=datetime.strptime("02:30", "%H:%M").time())
    jq.run_repeating(hourly_drawdown_check,  interval=3600, first=120)

    logger.info("[monitor] Monitoring jobs registered.")
