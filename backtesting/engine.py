"""
backtesting/engine.py — Backtesting orchestration layer.

Coordinates: data fetch → replay → metrics → persistence.
"""
import logging
from datetime import datetime, timezone

from backtesting.replay import run_replay
from backtesting.metrics import calculate_metrics
from storage import database as db

logger = logging.getLogger(__name__)

VALID_STRATEGIES  = ("fib", "fibonacci", "smc", "confluence")
VALID_TIMEFRAMES  = ("15m", "1H", "4H", "1D")
VALID_LOOKBACKS   = ("7d", "14d", "30d", "60d", "90d")

DEFAULT_TF       = "1H"
DEFAULT_LOOKBACK = "30d"


def parse_backtest_args(args: list[str]) -> tuple[str, str, str, str | None]:
    """
    Parse /backtest command arguments.
    Usage: /backtest <strategy> [timeframe] [lookback]
    Returns (strategy, timeframe, lookback, error_msg | None)
    """
    if not args:
        return "", "", "", "Usage: /backtest fib|smc|confluence [1H|4H|15m|1D] [30d|60d|90d]"

    strategy = args[0].lower().strip()
    if strategy == "fibonacci":
        strategy = "fib"

    if strategy not in VALID_STRATEGIES:
        return "", "", "", (
            f"Unknown strategy '{strategy}'.\n"
            f"Valid: fib, smc, confluence\n\n"
            f"Example: /backtest fib 1H 30d"
        )

    timeframe = DEFAULT_TF
    lookback  = DEFAULT_LOOKBACK

    if len(args) >= 2:
        tf_arg = args[1].upper()
        if tf_arg in ("1H", "4H", "15M", "1D"):
            timeframe = tf_arg.replace("15M", "15m")
        else:
            return strategy, "", "", (
                f"Unknown timeframe '{args[1]}'.\n"
                f"Valid: 15m, 1H, 4H, 1D"
            )

    if len(args) >= 3:
        lb_arg = args[2].lower()
        if lb_arg in VALID_LOOKBACKS:
            lookback = lb_arg
        else:
            return strategy, timeframe, "", (
                f"Unknown lookback '{args[2]}'.\n"
                f"Valid: 7d, 14d, 30d, 60d, 90d"
            )

    return strategy, timeframe, lookback, None


def run_backtest(
    strategy: str,
    timeframe: str = DEFAULT_TF,
    lookback: str  = DEFAULT_LOOKBACK,
) -> tuple[dict, dict, str | None]:
    """
    Run a complete backtest.

    Returns:
        metrics: dict — performance metrics
        meta:    dict — run metadata
        error:   str | None — error message if failed
    """
    logger.info("Starting backtest: strategy=%s tf=%s lookback=%s", strategy, timeframe, lookback)

    try:
        trades, meta = run_replay(strategy, timeframe, lookback)
        if meta.get("error"):
            return {}, meta, meta["error"]

        if not trades:
            return {}, meta, f"No trades generated for {strategy.upper()} on {timeframe} ({lookback})."

        metrics = calculate_metrics(trades)

        run_id = db.save_backtest_run(
            strategy=strategy,
            timeframe=timeframe,
            lookback=lookback,
            total_trades=metrics["total_trades"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            max_drawdown=metrics["max_drawdown"],
            sharpe=metrics["sharpe_like"],
            total_pnl=metrics["total_pnl"],
        )

        for trade in trades:
            db.save_backtest_trade(run_id=run_id, trade=trade)

        meta["run_id"] = run_id
        logger.info("Backtest complete: run_id=%s trades=%d win_rate=%.1f%%",
                    run_id, metrics["total_trades"], metrics["win_rate"])

        return metrics, meta, None

    except Exception as e:
        logger.error("Backtest engine error: %s", e, exc_info=True)
        return {}, {}, f"Backtest error: {e}"
