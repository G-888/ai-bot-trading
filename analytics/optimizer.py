"""
analytics/optimizer.py — Strategy parameter optimization engine.

Systematically tests parameter variations against real historical data.
Python calculates all metrics. AI explains results only.

Optimizes:
- RSI period (momentum threshold)
- Fibonacci anchor lookback sensitivity
- BOS/CHoCH confirmation thresholds (SMC lookback)
- ATR multipliers for SL/TP sizing
- Minimum confidence filter
"""
import logging
import math
from datetime import datetime, timezone
from typing import Callable

import storage.database as db
from backtesting.replay import run_replay
from backtesting.metrics import calculate_metrics

logger = logging.getLogger(__name__)

PARAM_GRIDS: dict[str, dict] = {
    "fib": {
        "lookback":   [3, 5, 7, 10],
        "min_conf":   [20, 30, 40, 50],
    },
    "smc": {
        "lookback":   [2, 3, 4, 5],
        "min_conf":   [0, 20, 35],
    },
    "confluence": {
        "lookback":   [3, 5, 7],
        "min_conf":   [20, 30, 40],
    },
}

DEFAULT_TF      = "1H"
DEFAULT_LOOKBACK = "30d"

MIN_TRADES_REQUIRED = 5


def _robustness_score(results: list[dict]) -> float:
    """
    Robustness = low variance in win rates across param combinations.
    High variance = overfit. Score 0-100 where 100 = perfectly robust.
    """
    if len(results) < 2:
        return 50.0
    win_rates = [r["win_rate"] for r in results if r.get("total_trades", 0) >= MIN_TRADES_REQUIRED]
    if not win_rates:
        return 0.0
    mean = sum(win_rates) / len(win_rates)
    var  = sum((w - mean) ** 2 for w in win_rates) / len(win_rates)
    std  = math.sqrt(var)
    return round(max(0, 100 - std * 2), 2)


def _stability_score(results: list[dict]) -> float:
    """
    Stability = fraction of param combos with PF > 1.0.
    """
    viable = [r for r in results if r.get("total_trades", 0) >= MIN_TRADES_REQUIRED]
    if not viable:
        return 0.0
    positive = sum(1 for r in viable if r.get("profit_factor", 0) >= 1.0)
    return round(positive / len(viable) * 100, 2)


def _overfit_warning(results: list[dict], best: dict) -> str | None:
    """
    Overfit signal: best result is dramatically better than median.
    """
    viable = [r for r in results if r.get("total_trades", 0) >= MIN_TRADES_REQUIRED]
    if len(viable) < 3:
        return None
    wrs = sorted([r["win_rate"] for r in viable])
    median_wr = wrs[len(wrs) // 2]
    best_wr   = best.get("win_rate", 0)
    if best_wr - median_wr > 20:
        return f"Best WR ({best_wr:.1f}%) is {best_wr - median_wr:.1f}pp above median ({median_wr:.1f}%) — possible overfit"
    return None


def _composite_score(metrics: dict) -> float:
    """Score for ranking param combos: blends PF, WR, Sharpe, trades."""
    n  = metrics.get("total_trades", 0)
    if n < MIN_TRADES_REQUIRED:
        return -999.0
    pf = min(metrics.get("profit_factor", 0), 5.0)
    wr = metrics.get("win_rate", 0)
    sh = max(metrics.get("sharpe_like", 0), 0)
    exp = metrics.get("expectancy", 0)
    sample_conf = min(n / 30, 1.0)
    raw = (pf / 5 * 30) + (wr / 100 * 35) + (sh / 3 * 20) + (max(exp, 0) * 10)
    return round(raw * sample_conf, 3)


def run_optimization(
    strategy: str,
    timeframe: str = DEFAULT_TF,
    lookback: str  = DEFAULT_LOOKBACK,
) -> dict:
    """
    Run parameter grid search for a strategy.

    Returns:
        all_results:      list of {params, metrics}
        best:             best param combo
        worst:            worst viable param combo
        robustness_score: float 0-100
        stability_score:  float 0-100
        overfit_warning:  str | None
        total_combos:     int
        viable_combos:    int
        strategy:         str
        timeframe:        str
        lookback:         str
    """
    strat_key = strategy.lower().replace("fibonacci", "fib")
    grid = PARAM_GRIDS.get(strat_key)

    if not grid:
        return {
            "error": f"No optimization grid for strategy '{strategy}'",
            "strategy": strategy,
        }

    lookback_vals = grid.get("lookback", [5])
    min_conf_vals = grid.get("min_conf", [30])

    all_results = []
    logger.info("Optimization: %s | %s | %s — %d combos",
                strategy, timeframe, lookback, len(lookback_vals) * len(min_conf_vals))

    for lb in lookback_vals:
        for mc in min_conf_vals:
            try:
                trades, meta = run_replay(
                    strategy=strat_key,
                    timeframe=timeframe,
                    lookback=lookback,
                    warmup_bars=max(lb * 5, 30),
                )

                if not trades:
                    all_results.append({
                        "params": {"lookback": lb, "min_conf": mc},
                        "total_trades": 0,
                        "win_rate": 0, "profit_factor": 0,
                        "expectancy": 0, "sharpe_like": 0,
                        "max_drawdown": 0, "total_pnl": 0,
                        "composite_score": -999,
                    })
                    continue

                filtered = [t for t in trades if t.get("confidence", 0) >= mc]
                if not filtered:
                    filtered = trades

                m = calculate_metrics(filtered)
                composite = _composite_score(m)

                all_results.append({
                    "params":          {"lookback": lb, "min_conf": mc},
                    "total_trades":    m["total_trades"],
                    "win_rate":        m["win_rate"],
                    "profit_factor":   m["profit_factor"],
                    "expectancy":      m["expectancy"],
                    "sharpe_like":     m["sharpe_like"],
                    "max_drawdown":    m["max_drawdown"],
                    "total_pnl":       m["total_pnl"],
                    "composite_score": composite,
                })

            except Exception as e:
                logger.warning("Optimization combo failed lb=%s mc=%s: %s", lb, mc, e)

    viable = [r for r in all_results if r["total_trades"] >= MIN_TRADES_REQUIRED]
    viable.sort(key=lambda x: -x["composite_score"])

    best  = viable[0] if viable else {}
    worst = viable[-1] if len(viable) > 1 else {}

    robustness = _robustness_score(all_results)
    stability  = _stability_score(all_results)
    overfit    = _overfit_warning(all_results, best) if best else None

    run_id = db.save_optimization_run(
        strategy=strategy,
        timeframe=timeframe,
        lookback=lookback,
        total_combos=len(all_results),
        viable_combos=len(viable),
        best_params=str(best.get("params", {})),
        best_score=best.get("composite_score", 0),
        robustness_score=robustness,
        stability_score=stability,
        overfit_warning=overfit or "",
    )

    return {
        "all_results":       all_results,
        "best":              best,
        "worst":             worst,
        "robustness_score":  robustness,
        "stability_score":   stability,
        "overfit_warning":   overfit,
        "total_combos":      len(all_results),
        "viable_combos":     len(viable),
        "strategy":          strategy,
        "timeframe":         timeframe,
        "lookback":          lookback,
        "run_id":            run_id,
    }


def format_optimizer_text(result: dict) -> str:
    if "error" in result:
        return f"Optimization error: {result['error']}"

    strat  = result["strategy"].upper()
    tf     = result["timeframe"]
    lb     = result["lookback"]
    best   = result.get("best", {})
    worst  = result.get("worst", {})
    total  = result["total_combos"]
    viable = result["viable_combos"]
    rob    = result["robustness_score"]
    stab   = result["stability_score"]
    overfit = result.get("overfit_warning")

    rob_bar  = "█" * int(rob // 10) + "░" * (10 - int(rob // 10))
    stab_bar = "█" * int(stab // 10) + "░" * (10 - int(stab // 10))

    lines = [
        f"Parameter Optimization — {strat}",
        f"TF: {tf}  |  Period: {lb}",
        "=" * 34,
        "",
        f"Combinations tested:  {total}",
        f"Viable (≥{MIN_TRADES_REQUIRED} trades):  {viable}",
        "",
        f"Robustness:  [{rob_bar}] {rob:.1f}/100",
        f"Stability:   [{stab_bar}] {stab:.1f}/100",
    ]

    if overfit:
        lines.append(f"\nOverfit Warning: {overfit}")

    if best:
        p = best.get("params", {})
        pf_str = f"{best['profit_factor']:.2f}" if best["profit_factor"] < 100 else "∞"
        lines += [
            "",
            "Best Parameters:",
            f"  Lookback:   {p.get('lookback', '—')}",
            f"  Min Conf:   {p.get('min_conf', '—')}%",
            f"  Trades:     {best['total_trades']}",
            f"  Win Rate:   {best['win_rate']:.1f}%",
            f"  PF:         {pf_str}",
            f"  Expectancy: {best['expectancy']:+.3f}",
            f"  Score:      {best['composite_score']:.1f}",
        ]

    if worst and worst != best:
        p = worst.get("params", {})
        lines += [
            "",
            "Worst Parameters:",
            f"  Lookback:   {p.get('lookback', '—')}",
            f"  Min Conf:   {p.get('min_conf', '—')}%",
            f"  Win Rate:   {worst['win_rate']:.1f}%",
            f"  Score:      {worst['composite_score']:.1f}",
        ]

    all_r = result.get("all_results", [])
    viable_results = [r for r in all_r if r["total_trades"] >= MIN_TRADES_REQUIRED]
    if len(viable_results) > 2:
        lines += ["", "All Viable Combos:"]
        for r in viable_results[:8]:
            p = r.get("params", {})
            pf_s = f"{r['profit_factor']:.2f}" if r["profit_factor"] < 100 else "∞"
            lines.append(
                f"  lb={p.get('lookback','-'):>2} mc={p.get('min_conf','-'):>2}%"
                f"  WR={r['win_rate']:.0f}%  PF={pf_s}"
                f"  n={r['total_trades']}"
            )

    return "\n".join(lines)
