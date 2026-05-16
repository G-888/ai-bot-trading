"""
market/data.py — XAUUSD data fetching and multi-timeframe assembly.

All calculations are done in Python. AI only receives the computed values.
"""
import logging
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

TICKER = "GC=F"


def fetch_ohlcv(period: str, interval: str) -> pd.DataFrame | None:
    """Return a clean OHLCV DataFrame or None on failure."""
    try:
        ticker = yf.Ticker(TICKER)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            return None
        df.index = df.index.tz_localize(None) if df.index.tzinfo is not None else df.index
        return df
    except Exception as e:
        logger.error("yfinance fetch failed (period=%s interval=%s): %s", period, interval, e)
        return None


def _tf_bias(df: pd.DataFrame, lookback: int, threshold: float = 0.3) -> tuple[str, float]:
    if len(df) < lookback + 1:
        return "Neutral", 0.0
    current = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-lookback])
    pct = (current - prev) / prev * 100
    if pct > threshold:
        return "Bullish", round(pct, 2)
    if pct < -threshold:
        return "Bearish", round(pct, 2)
    return "Neutral", round(pct, 2)


def _tf_sr(df: pd.DataFrame, lookback: int) -> tuple[float, float]:
    recent = df.tail(lookback)
    return round(float(recent["Low"].min()), 2), round(float(recent["High"].max()), 2)


def _momentum_label(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> str:
    if len(df) < slow + 1:
        return "Flat"
    closes = df["Close"]
    ema_fast = float(closes.ewm(span=fast, adjust=False).mean().iloc[-1])
    ema_slow = float(closes.ewm(span=slow, adjust=False).mean().iloc[-1])
    prev_fast = float(closes.ewm(span=fast, adjust=False).mean().iloc[-2])
    prev_slow = float(closes.ewm(span=slow, adjust=False).mean().iloc[-2])
    gap_now = ema_fast - ema_slow
    gap_prev = prev_fast - prev_slow
    if abs(gap_now) < abs(ema_slow) * 0.001:
        return "Flat"
    return "Accelerating" if gap_now > gap_prev else "Decelerating"


def _volatility_label(df: pd.DataFrame, lookback: int = 24) -> str:
    recent = df.tail(lookback)
    avg_range = float((recent["High"] - recent["Low"]).mean())
    price = float(recent["Close"].iloc[-1])
    vol_pct = avg_range / price * 100
    if vol_pct > 1.0:
        return "High"
    if vol_pct > 0.5:
        return "Medium"
    return "Low"


def _alignment_label(biases: list[str]) -> str:
    bull = biases.count("Bullish")
    bear = biases.count("Bearish")
    if bull == len(biases):
        return "Full Bull Alignment"
    if bear == len(biases):
        return "Full Bear Alignment"
    if bull > bear:
        return "Bullish Bias (partial)"
    if bear > bull:
        return "Bearish Bias (partial)"
    return "Conflicting Structure"


def fetch_gold_data() -> dict | None:
    """
    Fetch and compute multi-timeframe XAUUSD data.
    Returns a rich dict with 1H, 4H, and Daily computed fields.
    """
    try:
        h1 = fetch_ohlcv("5d", "1h")
        if h1 is None:
            return None

        current_price = round(float(h1["Close"].iloc[-1]), 2)

        h1_bias, h1_pct = _tf_bias(h1, lookback=6, threshold=0.15)
        h1_support, h1_resistance = _tf_sr(h1, lookback=24)
        volatility = _volatility_label(h1)

        h4 = fetch_ohlcv("30d", "4h")
        if h4 is not None and len(h4) > 10:
            h4_trend, h4_pct = _tf_bias(h4, lookback=10, threshold=0.3)
            h4_support, h4_resistance = _tf_sr(h4, lookback=30)
            h4_momentum = _momentum_label(h4)
        else:
            h4_trend, h4_pct = "Neutral", 0.0
            h4_support, h4_resistance = h1_support, h1_resistance
            h4_momentum = "Flat"
            h4 = h1

        d1 = fetch_ohlcv("90d", "1d")
        if d1 is not None and len(d1) > 14:
            d1_momentum, d1_pct = _tf_bias(d1, lookback=14, threshold=0.5)
            d1_support, d1_resistance = _tf_sr(d1, lookback=20)
            d1_ema_state = _momentum_label(d1, fast=9, slow=21)
        else:
            d1_momentum, d1_pct = "Neutral", 0.0
            d1_support, d1_resistance = h1_support, h1_resistance
            d1_ema_state = "Flat"
            d1 = h1

        alignment = _alignment_label([h1_bias, h4_trend, d1_momentum])

        return {
            "price": current_price,
            "volatility": volatility,
            "alignment": alignment,
            # 1H
            "h1_bias": h1_bias,
            "h1_pct": h1_pct,
            "h1_support": h1_support,
            "h1_resistance": h1_resistance,
            # 4H
            "h4_trend": h4_trend,
            "h4_pct": h4_pct,
            "h4_support": h4_support,
            "h4_resistance": h4_resistance,
            "h4_momentum": h4_momentum,
            # Daily
            "d1_momentum": d1_momentum,
            "d1_pct": d1_pct,
            "d1_support": d1_support,
            "d1_resistance": d1_resistance,
            "d1_ema_state": d1_ema_state,
            # Raw DataFrames
            "h1_df": h1,
            "h4_df": h4,
            "d1_df": d1,
            # Legacy aliases for chart/summary compatibility
            "support": h1_support,
            "resistance": h1_resistance,
            "trend": h4_trend,
            "pct_change": h4_pct,
            "closes": h1["Close"].tail(24).tolist(),
            "highs": h1["High"].tail(24).tolist(),
            "lows": h1["Low"].tail(24).tolist(),
            "volumes": h1["Volume"].tail(24).tolist(),
            "df": h1,
        }
    except Exception as e:
        logger.error("fetch_gold_data failed: %s", e)
        return None
