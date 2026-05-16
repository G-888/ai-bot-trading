"""
analytics/alerts.py — Telegram alert dispatcher for edge deterioration events.

Sends targeted alerts to all subscribed users when:
- edge health crosses threshold
- sudden drawdown spike detected
- regime mismatch detected

Uses stored chat IDs from the alerts table.
"""
import logging
from datetime import datetime, timezone

import storage.database as db

logger = logging.getLogger(__name__)

SEV_ICON = {"CRITICAL": "✗", "WARNING": "!", "INFO": "i"}


def _get_alert_chat_ids() -> list[int]:
    """Pull all distinct chat IDs that have alerts or summaries configured."""
    try:
        with db._lock, db._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT chat_id FROM price_alerts UNION "
                "SELECT DISTINCT chat_id FROM summary_settings"
            ).fetchall()
            return [r["chat_id"] for r in rows]
    except Exception:
        return []


async def dispatch_edge_alert(
    context,
    strategy: str,
    label: str,
    health_now: int,
    health_prev: int | None,
    alert_type: str,
    issues: list[dict],
    recommendations: list[str],
) -> None:
    """Send an edge health deterioration alert to all subscribed users."""
    chat_ids = _get_alert_chat_ids()
    if not chat_ids:
        logger.info("[alerts] No subscribed users — skipping edge alert for %s", strategy)
        return

    prev_str = f"{health_prev} → " if health_prev is not None else ""
    sev_label = "CRITICAL" if alert_type == "CRITICAL" else "WARNING"

    top_issues = [i for i in issues if i.get("severity") in ("CRITICAL", "WARNING")][:3]
    issue_lines = "\n".join(
        f"  {SEV_ICON.get(i.get('severity','?'), '?')} {i['msg']}"
        for i in top_issues
    ) if top_issues else "  No specific issues identified."

    rec_lines = "\n".join(f"  → {r}" for r in recommendations[:2]) if recommendations else ""

    text = (
        f"EDGE {sev_label} — {label.upper()}\n"
        f"{'=' * 30}\n\n"
        f"Edge Health: {prev_str}{health_now}/100\n\n"
        f"Issues Detected:\n{issue_lines}\n\n"
        + (f"Recommendations:\n{rec_lines}\n\n" if rec_lines else "")
        + f"Run /decay {strategy} for full analysis."
    )

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.warning("[alerts] Failed to send edge alert to %s: %s", chat_id, e)


async def dispatch_drawdown_alert(
    context,
    strategy: str,
    label: str,
    dd_now: float,
    dd_baseline: float,
) -> None:
    """Send a drawdown spike alert to all subscribed users."""
    chat_ids = _get_alert_chat_ids()
    if not chat_ids:
        return

    pct_above = (dd_now - dd_baseline) / dd_baseline * 100 if dd_baseline > 0 else 0

    text = (
        f"DRAWDOWN SPIKE — {label.upper()}\n"
        f"{'=' * 30}\n\n"
        f"Current DD: {dd_now:.2f} pts\n"
        f"Baseline:   {dd_baseline:.2f} pts\n"
        f"Spike:      +{pct_above:.0f}% above baseline\n\n"
        f"Consider reducing exposure until drawdown stabilises.\n\n"
        f"Run /diagnostics for full health check."
    )

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.warning("[alerts] Failed to send DD alert to %s: %s", chat_id, e)


async def dispatch_regime_alert(
    context,
    strategy: str,
    label: str,
    failing_regime: str,
    win_rate: float,
) -> None:
    """Send a regime mismatch alert to all subscribed users."""
    chat_ids = _get_alert_chat_ids()
    if not chat_ids:
        return

    text = (
        f"REGIME MISMATCH — {label.upper()}\n"
        f"{'=' * 30}\n\n"
        f"Strategy underperforming in {failing_regime} conditions.\n"
        f"Win Rate: {win_rate:.1f}%\n\n"
        f"Recommendation:\n"
        f"  → Suppress {strategy.upper()} signals during {failing_regime} regime.\n"
        f"  → Apply regime filter: /regimehealth\n\n"
        f"Run /decay for detailed decay analysis."
    )

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.warning("[alerts] Failed to send regime alert to %s: %s", chat_id, e)
