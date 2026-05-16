"""
backtesting/replay.py — Historical candle replay engine.

Walks through historical XAUUSD bars, runs strategy engines at each bar,
generates signals, and simulates trade outcomes.
All calculation is Python-native using real yfinance data.
"""
import logging
from datetime import datetime, timezone
from typing import Generator

import pandas as pd

from market.data import fetch_ohlcv
from market.indicators import atr
from strategies.fibonacci import run_fibonacci_analysis
from strategies.smc import run_smc_analysis
from market.regime import detect_regime

logger = logging.getLogger(__name__)

TF_CONFIG = {
    "15m": {"period": "60d",  "interval": "15m", "atr_mult_sl": 1.5, "atr_mult_tp": 3.0, "min_bars": 60},
    "1H":  {"period": "90d",  "interval": "1h",  "atr_mult_sl": 1.5, "atr_mult_tp": 3.0, "min_bars": 40},
    "4H":  {"period": "180d", "interval": "4h",  "atr_mult_sl": 2.0, "atr_mult_tp": 4.0, "min_bars": 30},
    "1D":  {"period": "730d", "interval": "1d",  "atr_mult_sl": 2.0, "atr_mult_tp": 4.0, "min_bars": 30},
}

LOOKBACK_MAP = {
    "7d":  7,
    "14d": 14,
    "30d": 30,
    "60d": 60,
    "90d": 90,
}


def _parse_lookback_days(lookback: str) -> int:
    return LOOKBACK_MAP.get(lookback.lower(), 30)


def _estimate_bars(days: int, interval: str) -> int:
    bars_per_day = {"15m": 96, "1h": 24, "4h": 6, "1d": 1}
    return days * bars_per_day.get(interval, 24)


def fetch_historical(timeframe: str, lookback_days: int) -> pd.DataFrame | None:
    """Fetch enough historical data for the replay window + warmup."""
    cfg = TF_CONFIG.get(timeframe.upper().replace("H", "H").replace("M", "m"))
    if cfg is None:
        cfg = TF_CONFIG.get("1H")

    interval = cfg["interval"]
    warmup_days = max(lookback_days * 2, 90)
    total_days = lookback_days + warmup_days

    period_str = f"{min(total_days, 729)}d"
    df = fetch_ohlcv(period_str, interval)
    return df


def _signal_from_strategy(strategy: str, df_slice: pd.DataFrame) -> tuple[str, float, float, float]:
    """
    Run a strategy on a data slice and return (bias, entry, sl, tp).
    Returns ("NEUTRAL", 0, 0, 0) if no signal.
    """
    try:
        if strategy in ("fib", "fibonacci"):
            result = run_fibonacci_analysis(df_slice)
            if result is None:
                return "NEUTRAL", 0, 0, 0
            conf = result.get("confluence_score", 0)
            if conf < 30:
                return "NEUTRAL", 0, 0, 0
            direction = result.get("direction", "")
            entry = float(df_slice["Close"].iloc[-1])
            atr_val = float(atr(df_slice, 14).iloc[-1]) if len(df_slice) > 14 else entry * 0.003

            if "retracement_up" in direction:
                sl = round(entry - atr_val * 1.5, 2)
                tp = round(entry + atr_val * 3.0, 2)
                return "BUY", entry, sl, tp
            elif "retracement_down" in direction:
                sl = round(entry + atr_val * 1.5, 2)
                tp = round(entry - atr_val * 3.0, 2)
                return "SELL", entry, sl, tp
            return "NEUTRAL", 0, 0, 0

        elif strategy == "smc":
            result = run_smc_analysis(df_slice)
            bias = result.get("overall_bias", "Neutral")
            if bias == "Neutral":
                return "NEUTRAL", 0, 0, 0
            choch = result.get("choch_count", 0)
            if choch == 0:
                return "NEUTRAL", 0, 0, 0
            entry = float(df_slice["Close"].iloc[-1])
            atr_val = float(atr(df_slice, 14).iloc[-1]) if len(df_slice) > 14 else entry * 0.003
            if "Bullish" in bias:
                sl = round(entry - atr_val * 1.5, 2)
                tp = round(entry + atr_val * 3.0, 2)
                return "BUY", entry, sl, tp
            else:
                sl = round(entry + atr_val * 1.5, 2)
                tp = round(entry - atr_val * 3.0, 2)
                return "SELL", entry, sl, tp

        elif strategy == "confluence":
            fib = run_fibonacci_analysis(df_slice)
            smc = run_smc_analysis(df_slice)

            fib_dir = ""
            if fib:
                fib_dir = fib.get("direction", "")
            smc_bias = smc.get("overall_bias", "Neutral")

            bull_signals = 0
            bear_signals = 0
            if "retracement_up" in fib_dir:
                bull_signals += 1
            elif "retracement_down" in fib_dir:
                bear_signals += 1
            if "Bullish" in smc_bias:
                bull_signals += 1
            elif "Bearish" in smc_bias:
                bear_signals += 1

            if bull_signals >= 2:
                direction = "BUY"
            elif bear_signals >= 2:
                direction = "SELL"
            else:
                return "NEUTRAL", 0, 0, 0

            entry = float(df_slice["Close"].iloc[-1])
            atr_val = float(atr(df_slice, 14).iloc[-1]) if len(df_slice) > 14 else entry * 0.003
            if direction == "BUY":
                sl = round(entry - atr_val * 1.5, 2)
                tp = round(entry + atr_val * 3.0, 2)
            else:
                sl = round(entry + atr_val * 1.5, 2)
                tp = round(entry - atr_val * 3.0, 2)
            return direction, entry, sl, tp

        return "NEUTRAL", 0, 0, 0

    except Exception as e:
        logger.debug("Signal extraction failed for %s: %s", strategy, e)
        return "NEUTRAL", 0, 0, 0


def _simulate_trade(
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    future_bars: pd.DataFrame,
    strategy: str,
    signal_ts: str,
    confidence: float = 0.0,
    session: str = "",
) -> dict:
    """
    Simulate a trade against future bars.
    Returns a completed trade dict.
    """
    max_hold = min(len(future_bars), 50)
    atr_val  = abs(entry - sl)
    rr_ratio = abs(tp - entry) / atr_val if atr_val > 0 else 0.0

    mae = 0.0
    mfe = 0.0

    for i, (ts, row) in enumerate(future_bars.iloc[:max_hold].iterrows()):
        high = float(row["High"])
        low  = float(row["Low"])

        if direction == "BUY":
            mfe = max(mfe, high - entry)
            mae = max(mae, entry - low)
            if high >= tp:
                return _make_trade(
                    direction, entry, sl, tp, rr_ratio, float(tp - entry),
                    i + 1, "TP_HIT", strategy, signal_ts, confidence, session, mae, mfe
                )
            if low <= sl:
                return _make_trade(
                    direction, entry, sl, tp, rr_ratio, float(sl - entry),
                    i + 1, "SL_HIT", strategy, signal_ts, confidence, session, mae, mfe
                )
        else:
            mfe = max(mfe, entry - low)
            mae = max(mae, high - entry)
            if low <= tp:
                return _make_trade(
                    direction, entry, sl, tp, rr_ratio, float(entry - tp),
                    i + 1, "TP_HIT", strategy, signal_ts, confidence, session, mae, mfe
                )
            if high >= sl:
                return _make_trade(
                    direction, entry, sl, tp, rr_ratio, float(entry - sl),
                    i + 1, "SL_HIT", strategy, signal_ts, confidence, session, mae, mfe
                )

    last_price = float(future_bars["Close"].iloc[min(max_hold - 1, len(future_bars) - 1)])
    pnl = (last_price - entry) if direction == "BUY" else (entry - last_price)
    return _make_trade(
        direction, entry, sl, tp, rr_ratio, pnl,
        max_hold, "TIMEOUT", strategy, signal_ts, confidence, session, mae, mfe
    )


def _make_trade(
    direction, entry, sl, tp, rr_ratio, pnl,
    duration_bars, exit_reason, strategy, signal_ts, confidence, session, mae, mfe
) -> dict:
    return {
        "direction":     direction,
        "entry":         round(entry, 2),
        "sl":            round(sl, 2),
        "tp":            round(tp, 2),
        "rr_ratio":      round(rr_ratio, 2),
        "rr_actual":     round(pnl / abs(entry - sl), 3) if abs(entry - sl) > 0 else 0.0,
        "pnl":           round(pnl, 2),
        "duration_bars": duration_bars,
        "exit_reason":   exit_reason,
        "strategy":      strategy,
        "confidence":    round(confidence, 1),
        "session":       session,
        "timestamp":     signal_ts,
        "mae":           round(mae, 2),
        "mfe":           round(mfe, 2),
    }


def run_replay(
    strategy: str,
    timeframe: str,
    lookback: str,
    warmup_bars: int = 50,
    step: int = 3,
) -> tuple[list[dict], dict]:
    """
    Run a full historical replay for the given strategy.

    Args:
        strategy:     'fib' | 'smc' | 'confluence'
        timeframe:    '15m' | '1H' | '4H' | '1D'
        lookback:     '30d' | '60d' | '90d' etc.
        warmup_bars:  bars used to prime indicators before signals start
        step:         replay step (skip every N bars to avoid trade overlap)

    Returns:
        (trades: list[dict], meta: dict)
    """
    lookback_days = _parse_lookback_days(lookback)
    df = fetch_historical(timeframe, lookback_days)

    if df is None or df.empty:
        return [], {"error": "No historical data available", "timeframe": timeframe}

    tf_key = timeframe.upper()
    if tf_key not in TF_CONFIG:
        tf_key = "1H"
    cfg = TF_CONFIG[tf_key]

    min_bars = cfg["min_bars"] + warmup_bars

    if len(df) < min_bars:
        return [], {"error": f"Insufficient data: {len(df)} bars (need {min_bars})", "timeframe": timeframe}

    replay_bars = _estimate_bars(lookback_days, cfg["interval"])
    start_idx   = max(len(df) - replay_bars - warmup_bars, warmup_bars)

    trades: list[dict] = []
    active_trade: dict | None = None
    active_until: int = -1

    for i in range(start_idx, len(df) - step, step):
        if active_trade is not None and i <= active_until:
            continue

        window = df.iloc[max(0, i - warmup_bars): i]
        if len(window) < cfg["min_bars"]:
            continue

        ts = str(df.index[i])
        bias, entry, sl, tp = _signal_from_strategy(strategy, window)

        if bias == "NEUTRAL":
            continue

        future = df.iloc[i:]
        if len(future) < 3:
            continue

        regime  = detect_regime(window)
        session = _guess_session(df.index[i])

        trade = _simulate_trade(
            direction=bias,
            entry=entry, sl=sl, tp=tp,
            future_bars=future,
            strategy=strategy,
            signal_ts=ts,
            confidence=0.0,
            session=session,
        )

        trade["regime"] = regime.get("label", "Unknown")
        trades.append(trade)
        active_trade = trade
        active_until = i + trade["duration_bars"]

    meta = {
        "strategy":   strategy,
        "timeframe":  timeframe,
        "lookback":   lookback,
        "total_bars": len(df),
        "start_idx":  start_idx,
        "signals_generated": len(trades),
    }
    return trades, meta


def _guess_session(ts) -> str:
    try:
        if hasattr(ts, "hour"):
            h = ts.hour
        else:
            from datetime import datetime
            h = datetime.fromisoformat(str(ts)).hour
        if 0 <= h < 8:
            return "Asia"
        if 8 <= h < 13:
            return "London"
        if 13 <= h < 16:
            return "London/NY Overlap"
        if 16 <= h < 21:
            return "New York"
        return "Dead Zone"
    except Exception:
        return "Unknown"
