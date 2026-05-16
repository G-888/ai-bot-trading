"""
backtesting/metrics.py — Performance metric calculations for backtests.

All statistics computed in pure Python/pandas. No mocked data.
"""
import math
import logging
from typing import List

logger = logging.getLogger(__name__)


def calculate_metrics(trades: List[dict]) -> dict:
    """
    Compute full performance metrics from a list of closed trades.

    Each trade dict must contain:
        pnl            float  — dollar/point profit or loss
        rr_actual      float  — actual R:R achieved
        duration_bars  int    — bars held until exit
        exit_reason    str    — 'TP_HIT' | 'SL_HIT' | 'TIMEOUT'
        strategy       str    — strategy source label
        entry          float
        sl             float
        tp             float
        timestamp      str    — entry timestamp ISO

    Returns full metrics dict.
    """
    if not trades:
        return _empty_metrics()

    closed = [t for t in trades if t.get("exit_reason") in ("TP_HIT", "SL_HIT", "TIMEOUT")]
    if not closed:
        return _empty_metrics()

    n = len(closed)
    winners = [t for t in closed if t["pnl"] > 0]
    losers  = [t for t in closed if t["pnl"] <= 0]

    win_rate  = len(winners) / n
    loss_rate = len(losers) / n

    total_pnl    = sum(t["pnl"] for t in closed)
    gross_profit = sum(t["pnl"] for t in winners) if winners else 0.0
    gross_loss   = abs(sum(t["pnl"] for t in losers)) if losers else 0.0

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_win  = gross_profit / len(winners) if winners else 0.0
    avg_loss = gross_loss   / len(losers)  if losers  else 0.0

    avg_rr   = sum(t["rr_actual"] for t in closed) / n
    avg_duration = sum(t["duration_bars"] for t in closed) / n

    expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)

    equity_curve = _build_equity_curve(closed)
    max_drawdown = _max_drawdown(equity_curve)

    sharpe = _sharpe_like(closed)

    strategy_perf = _strategy_breakdown(closed)

    mae_avg = sum(t.get("mae", 0) for t in closed) / n
    mfe_avg = sum(t.get("mfe", 0) for t in closed) / n

    streak_win, streak_loss = _streak(closed)

    return {
        "total_trades":   n,
        "win_rate":       round(win_rate  * 100, 2),
        "loss_rate":      round(loss_rate * 100, 2),
        "total_pnl":      round(total_pnl, 2),
        "gross_profit":   round(gross_profit, 2),
        "gross_loss":     round(gross_loss, 2),
        "profit_factor":  round(profit_factor, 3),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "avg_rr":         round(avg_rr, 3),
        "avg_duration_bars": round(avg_duration, 1),
        "expectancy":     round(expectancy, 2),
        "max_drawdown":   round(max_drawdown, 2),
        "sharpe_like":    round(sharpe, 3),
        "mae_avg":        round(mae_avg, 2),
        "mfe_avg":        round(mfe_avg, 2),
        "max_win_streak": streak_win,
        "max_loss_streak": streak_loss,
        "equity_curve":   equity_curve,
        "strategy_breakdown": strategy_perf,
    }


def _empty_metrics() -> dict:
    return {
        "total_trades": 0,
        "win_rate": 0.0, "loss_rate": 0.0,
        "total_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
        "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "avg_rr": 0.0, "avg_duration_bars": 0.0,
        "expectancy": 0.0, "max_drawdown": 0.0, "sharpe_like": 0.0,
        "mae_avg": 0.0, "mfe_avg": 0.0,
        "max_win_streak": 0, "max_loss_streak": 0,
        "equity_curve": [], "strategy_breakdown": {},
    }


def _build_equity_curve(trades: List[dict]) -> List[float]:
    curve = [0.0]
    running = 0.0
    for t in trades:
        running += t["pnl"]
        curve.append(round(running, 2))
    return curve


def _max_drawdown(equity_curve: List[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe_like(trades: List[dict]) -> float:
    """Simplified Sharpe using per-trade PnL as returns."""
    if len(trades) < 2:
        return 0.0
    pnls = [t["pnl"] for t in trades]
    n    = len(pnls)
    mean = sum(pnls) / n
    variance = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std  = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return mean / std * math.sqrt(n)


def _strategy_breakdown(trades: List[dict]) -> dict:
    grouped: dict[str, List[dict]] = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        grouped.setdefault(s, []).append(t)

    result = {}
    for strat, strat_trades in grouped.items():
        n = len(strat_trades)
        wins = [t for t in strat_trades if t["pnl"] > 0]
        total_pnl = sum(t["pnl"] for t in strat_trades)
        result[strat] = {
            "trades":   n,
            "wins":     len(wins),
            "win_rate": round(len(wins) / n * 100, 1) if n > 0 else 0.0,
            "total_pnl": round(total_pnl, 2),
            "avg_rr":   round(sum(t["rr_actual"] for t in strat_trades) / n, 3) if n > 0 else 0.0,
        }
    return result


def _streak(trades: List[dict]) -> tuple[int, int]:
    max_win = 0
    max_loss = 0
    cur_win = 0
    cur_loss = 0
    for t in trades:
        if t["pnl"] > 0:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        max_win  = max(max_win,  cur_win)
        max_loss = max(max_loss, cur_loss)
    return max_win, max_loss


def format_metrics_text(metrics: dict, strategy: str, timeframe: str, lookback: str) -> str:
    """Format performance metrics as a Telegram-ready report."""
    n  = metrics["total_trades"]
    if n == 0:
        return f"Backtest: {strategy.upper()} | {timeframe} | {lookback}\n\nNo trades generated."

    pf = metrics["profit_factor"]
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"

    conf_bar_wr = "█" * int(metrics["win_rate"] // 10) + "░" * (10 - int(metrics["win_rate"] // 10))

    lines = [
        f"XAUUSD Backtest Report",
        f"Strategy: {strategy.upper()}  |  TF: {timeframe}  |  Period: {lookback}",
        f"{'─' * 32}",
        f"",
        f"Trades:        {n}",
        f"Win Rate:      [{conf_bar_wr}] {metrics['win_rate']:.1f}%",
        f"Loss Rate:     {metrics['loss_rate']:.1f}%",
        f"",
        f"Total PnL:     {metrics['total_pnl']:+.2f} pts",
        f"Profit Factor: {pf_str}",
        f"Expectancy:    {metrics['expectancy']:+.2f} pts/trade",
        f"",
        f"Avg RR:        {metrics['avg_rr']:.2f}",
        f"Avg Win:       {metrics['avg_win']:+.2f} pts",
        f"Avg Loss:      {metrics['avg_loss']:-.2f} pts",
        f"",
        f"Max Drawdown:  {metrics['max_drawdown']:.2f} pts",
        f"Sharpe:        {metrics['sharpe_like']:.2f}",
        f"Avg Duration:  {metrics['avg_duration_bars']:.0f} bars",
        f"",
        f"Best Streak:   {metrics['max_win_streak']}W  /  {metrics['max_loss_streak']}L",
    ]

    sb = metrics.get("strategy_breakdown", {})
    if len(sb) > 1:
        lines.append("")
        lines.append("Strategy Breakdown:")
        for strat, st in sb.items():
            lines.append(f"  {strat:<14} {st['win_rate']:.0f}% WR  {st['total_pnl']:+.1f}pts")

    return "\n".join(lines)
