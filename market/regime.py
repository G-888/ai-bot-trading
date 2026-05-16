"""
market/regime.py — Market Regime Detection Engine.

Detects: Trending, Ranging, Volatile, Compression, Expansion.
Python computes all regime classifications. AI only explains.
"""
import logging
import pandas as pd

from market.indicators import atr, ema, rsi

logger = logging.getLogger(__name__)

REGIMES = {
    "TRENDING_BULL":   "Trending Bullish",
    "TRENDING_BEAR":   "Trending Bearish",
    "RANGING":         "Ranging",
    "VOLATILE":        "Volatile",
    "COMPRESSION":     "Compression",
    "EXPANSION":       "Expansion",
    "UNKNOWN":         "Unknown",
}


def _atr_percentile(df: pd.DataFrame, period: int = 14, lookback: int = 50) -> float:
    """Return ATR as a % of price, then compare vs recent history."""
    if len(df) < period + 2:
        return 0.5
    atr_series = atr(df, period)
    recent = atr_series.dropna().tail(lookback)
    if recent.empty:
        return 0.5
    current_atr = float(atr_series.iloc[-1])
    pct_rank = float((recent < current_atr).mean())
    return round(pct_rank, 4)


def _ema_slope(df: pd.DataFrame, period: int = 20) -> float:
    """Slope of the EMA as % change per bar."""
    if len(df) < period + 2:
        return 0.0
    ema_s = ema(df["Close"], period)
    current = float(ema_s.iloc[-1])
    prev = float(ema_s.iloc[-5]) if len(ema_s) >= 5 else float(ema_s.iloc[0])
    if prev == 0:
        return 0.0
    return round((current - prev) / prev * 100, 4)


def _price_vs_ema(df: pd.DataFrame, period: int = 20) -> float:
    """How far price is from EMA as % of price."""
    if len(df) < period:
        return 0.0
    ema_s = ema(df["Close"], period)
    price = float(df["Close"].iloc[-1])
    ema_val = float(ema_s.iloc[-1])
    if ema_val == 0:
        return 0.0
    return round((price - ema_val) / ema_val * 100, 4)


def _bollinger_width(df: pd.DataFrame, period: int = 20) -> float:
    """Bollinger Band width as % of middle band."""
    if len(df) < period:
        return 0.0
    closes = df["Close"]
    mid = float(closes.rolling(period).mean().iloc[-1])
    std = float(closes.rolling(period).std().iloc[-1])
    if mid == 0:
        return 0.0
    return round((std * 4) / mid * 100, 4)


def _high_low_range(df: pd.DataFrame, bars: int = 20) -> float:
    """High-low range of last N bars as % of price."""
    if len(df) < bars:
        bars = len(df)
    recent = df.tail(bars)
    high = float(recent["High"].max())
    low = float(recent["Low"].min())
    price = float(df["Close"].iloc[-1])
    if price == 0:
        return 0.0
    return round((high - low) / price * 100, 4)


def detect_regime(df: pd.DataFrame) -> dict:
    """
    Full market regime detection.

    Returns:
        regime: str — one of REGIMES keys
        label: str — human label
        atr_pct: float — ATR percentile rank (0-1)
        ema_slope_pct: float — EMA slope % per bar
        bb_width: float — Bollinger Band width %
        hl_range: float — High-low range %
        trending_score: float — 0-1 trending confidence
        ranging_score: float — 0-1 ranging confidence
        volatility_score: float — 0-1 volatility level
    """
    try:
        atr_pct = _atr_percentile(df, period=14, lookback=50)
        slope = _ema_slope(df, period=20)
        dist_from_ema = _price_vs_ema(df, period=20)
        bb_width = _bollinger_width(df, period=20)
        hl_range = _high_low_range(df, bars=20)
        rsi_val = float(rsi(df["Close"], 14).iloc[-1]) if len(df) > 14 else 50.0

        trending_score = min(1.0, (abs(slope) * 10 + abs(dist_from_ema) * 5) / 15)
        ranging_score = max(0.0, 1.0 - trending_score - (atr_pct - 0.5) * 0.5)
        volatility_score = atr_pct

        if atr_pct > 0.80 and bb_width > 0.8:
            regime = "VOLATILE"
        elif abs(slope) < 0.05 and hl_range < 0.5 and bb_width < 0.3:
            regime = "COMPRESSION"
        elif atr_pct > 0.70 and abs(slope) > 0.1:
            regime = "EXPANSION"
        elif abs(slope) > 0.08 and abs(dist_from_ema) > 0.2:
            if slope > 0:
                regime = "TRENDING_BULL"
            else:
                regime = "TRENDING_BEAR"
        elif hl_range < 0.6 and abs(slope) < 0.06:
            regime = "RANGING"
        else:
            if slope > 0.04:
                regime = "TRENDING_BULL"
            elif slope < -0.04:
                regime = "TRENDING_BEAR"
            else:
                regime = "RANGING"

        return {
            "regime": regime,
            "label": REGIMES[regime],
            "atr_pct": atr_pct,
            "ema_slope_pct": slope,
            "dist_from_ema": dist_from_ema,
            "bb_width": bb_width,
            "hl_range": hl_range,
            "rsi": round(rsi_val, 1),
            "trending_score": round(trending_score, 3),
            "ranging_score": round(ranging_score, 3),
            "volatility_score": round(volatility_score, 3),
        }

    except Exception as e:
        logger.error("Regime detection failed: %s", e)
        return {
            "regime": "UNKNOWN",
            "label": REGIMES["UNKNOWN"],
            "atr_pct": 0.5,
            "ema_slope_pct": 0.0,
            "dist_from_ema": 0.0,
            "bb_width": 0.0,
            "hl_range": 0.0,
            "rsi": 50.0,
            "trending_score": 0.0,
            "ranging_score": 0.5,
            "volatility_score": 0.5,
        }


def get_regime_vote_weights(regime: str) -> dict:
    """
    Return strategy vote weights adjusted for the current regime.
    Weights always sum to 1.0.
    """
    base = {
        "smc":        0.25,
        "fibonacci":  0.20,
        "momentum":   0.20,
        "session":    0.15,
        "confluence": 0.20,
    }

    if regime in ("TRENDING_BULL", "TRENDING_BEAR"):
        return {
            "smc":        0.30,
            "fibonacci":  0.20,
            "momentum":   0.25,
            "session":    0.10,
            "confluence": 0.15,
        }
    if regime == "RANGING":
        return {
            "smc":        0.25,
            "fibonacci":  0.30,
            "momentum":   0.10,
            "session":    0.15,
            "confluence": 0.20,
        }
    if regime == "VOLATILE":
        return {
            "smc":        0.20,
            "fibonacci":  0.15,
            "momentum":   0.15,
            "session":    0.25,
            "confluence": 0.25,
        }
    if regime == "COMPRESSION":
        return {
            "smc":        0.20,
            "fibonacci":  0.25,
            "momentum":   0.10,
            "session":    0.20,
            "confluence": 0.25,
        }
    if regime == "EXPANSION":
        return {
            "smc":        0.30,
            "fibonacci":  0.15,
            "momentum":   0.30,
            "session":    0.10,
            "confluence": 0.15,
        }
    return base


def should_suppress_signal(regime: dict, confidence: float, timeframe_conflict: float) -> tuple[bool, str]:
    """
    Return (suppress: bool, reason: str).
    Suppresses signal when conditions are unsuitable.
    """
    r = regime.get("regime", "UNKNOWN")
    vol = regime.get("volatility_score", 0.5)
    trending = regime.get("trending_score", 0.0)

    if confidence < 25:
        return True, "Confidence too weak (<25)"
    if timeframe_conflict > 0.7:
        return True, "Excessive timeframe conflict (>70%)"
    if vol < 0.15:
        return True, "Volatility too low — no tradeable range"
    if r == "UNKNOWN":
        return True, "Regime unclear — insufficient data"
    if r == "VOLATILE" and confidence < 45:
        return True, "Volatile regime requires confidence ≥45"
    return False, ""
