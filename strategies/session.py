"""
strategies/session.py — Trading session intelligence.

Detects Asia / London / New York sessions, session bias, and manipulation patterns.
All logic is pure Python.
"""
import logging
from datetime import datetime, timezone, time

import pandas as pd

logger = logging.getLogger(__name__)

# UTC session windows (hour, minute)
SESSIONS = {
    "Asia":       (time(0, 0),  time(8, 0)),
    "London":     (time(8, 0),  time(16, 0)),
    "New York":   (time(13, 0), time(21, 0)),
    "Dead Zone":  (time(21, 0), time(23, 59)),
}

OVERLAP = {
    "London/NY Overlap": (time(13, 0), time(16, 0)),
}

# Typical gold behaviour per session
SESSION_CHARACTERISTICS = {
    "Asia":     {"volatility": "Low",    "pattern": "Compression / Range", "bias_note": "Sets the liquidity pool for London"},
    "London":   {"volatility": "High",   "pattern": "Manipulation then Direction", "bias_note": "Primary directional session"},
    "New York": {"volatility": "High",   "pattern": "Continuation or Reversal", "bias_note": "Confirms or rejects London move"},
    "London/NY Overlap": {"volatility": "Very High", "pattern": "Trend continuation", "bias_note": "Highest volume window"},
    "Dead Zone": {"volatility": "Very Low", "pattern": "Consolidation", "bias_note": "Avoid trading this window"},
}


def get_current_session(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    t = dt.time()

    overlap_start, overlap_end = time(13, 0), time(16, 0)
    if overlap_start <= t <= overlap_end:
        return "London/NY Overlap"

    for name, (start, end) in SESSIONS.items():
        if start <= t <= end:
            return name

    return "Dead Zone"


def get_session_characteristics(session: str) -> dict:
    return SESSION_CHARACTERISTICS.get(session, {
        "volatility": "Unknown",
        "pattern": "Unknown",
        "bias_note": "Unknown",
    })


def _session_candles(df: pd.DataFrame, session_name: str) -> pd.DataFrame:
    """Filter dataframe to candles within the given session hours (UTC)."""
    if df.empty:
        return df
    session_map = {**SESSIONS, **OVERLAP}
    if session_name not in session_map:
        return df
    start, end = session_map[session_name]
    times = df.index.time if hasattr(df.index, 'time') else [row.time() for row in df.index]
    mask = [(t >= start and t <= end) for t in times]
    return df[mask]


def compute_session_ranges(h1_df: pd.DataFrame) -> dict:
    """
    Compute the price range for each session from the 1H dataframe.
    Returns high, low, and range size per session.
    """
    ranges = {}
    for session in ["Asia", "London", "New York"]:
        sub = _session_candles(h1_df, session)
        if sub.empty or len(sub) < 1:
            ranges[session] = {"high": None, "low": None, "range": None}
            continue
        high = round(float(sub["High"].max()), 2)
        low = round(float(sub["Low"].min()), 2)
        ranges[session] = {
            "high": high,
            "low": low,
            "range": round(high - low, 2),
        }
    return ranges


def detect_session_pattern(h1_df: pd.DataFrame, current_session: str) -> str:
    """
    Detect common session patterns:
    - London Sweep: London breaks Asia high/low then reverses
    - NY Continuation: NY continues London's direction
    - Asia Compression: Asia is tight range (low ATR)
    """
    try:
        asia_data = _session_candles(h1_df, "Asia")
        london_data = _session_candles(h1_df, "London")

        if asia_data.empty or london_data.empty:
            return "Insufficient data"

        asia_high = float(asia_data["High"].max())
        asia_low = float(asia_data["Low"].min())
        asia_range = asia_high - asia_low

        current_price = float(h1_df["Close"].iloc[-1])

        if asia_range < float(h1_df["Close"].mean()) * 0.002:
            if current_session == "Asia":
                return "Asia Compression — low volatility accumulation"

        if current_session in ("London", "London/NY Overlap"):
            london_high = float(london_data["High"].max())
            london_low = float(london_data["Low"].min())

            swept_high = london_high > asia_high
            swept_low = london_low < asia_low

            if swept_high and current_price < asia_high:
                return "London Liquidity Sweep (above Asia high) — bearish reversal risk"
            if swept_low and current_price > asia_low:
                return "London Liquidity Sweep (below Asia low) — bullish reversal risk"
            if swept_high and current_price > asia_high:
                return "London Breakout (above Asia high) — bullish continuation"
            if swept_low and current_price < asia_low:
                return "London Breakout (below Asia low) — bearish continuation"

        if current_session == "New York":
            if not london_data.empty:
                london_close = float(london_data["Close"].iloc[-1])
                london_open = float(london_data["Open"].iloc[0])
                london_bullish = london_close > london_open
                ny_bullish = current_price > london_close

                if london_bullish and ny_bullish:
                    return "NY Continuation (bullish) — trend aligned"
                if not london_bullish and not ny_bullish:
                    return "NY Continuation (bearish) — trend aligned"
                return "NY Reversal — counter-trend to London"

        return "No pattern detected"
    except Exception:
        return "Pattern analysis unavailable"


def get_continuation_probability(h1_df: pd.DataFrame, h4_df: pd.DataFrame) -> float:
    """
    Score continuation probability 0–100 based on:
    - TF alignment (40 pts)
    - Session type (30 pts)
    - Volatility regime (30 pts)
    """
    score = 50.0

    try:
        session = get_current_session()
        if session in ("London", "London/NY Overlap", "New York"):
            score += 15
        elif session == "Dead Zone":
            score -= 20

        h1_close = float(h1_df["Close"].iloc[-1])
        h1_prev = float(h1_df["Close"].iloc[-7]) if len(h1_df) > 7 else h1_close
        h4_close = float(h4_df["Close"].iloc[-1])
        h4_prev = float(h4_df["Close"].iloc[-11]) if len(h4_df) > 11 else h4_close

        h1_bull = h1_close > h1_prev
        h4_bull = h4_close > h4_prev
        if h1_bull == h4_bull:
            score += 15
        else:
            score -= 10

        from market.indicators import atr
        atr_val = float(atr(h1_df, 14).iloc[-1]) if len(h1_df) > 14 else 0
        avg_candle = abs(float(h1_df["Close"].iloc[-1]) - float(h1_df["Open"].iloc[-1]))
        if atr_val > 0 and avg_candle > atr_val * 0.5:
            score += 10

    except Exception:
        pass

    return round(min(max(score, 10), 90), 1)


def analyze_session(h1_df: pd.DataFrame, h4_df: pd.DataFrame) -> dict:
    """Full session intelligence snapshot."""
    current_session = get_current_session()
    characteristics = get_session_characteristics(current_session)
    pattern = detect_session_pattern(h1_df, current_session)
    ranges = compute_session_ranges(h1_df)
    continuation_pct = get_continuation_probability(h1_df, h4_df)

    asia_range = ranges.get("Asia", {})
    asia_range_str = (
        f"{asia_range['low']} – {asia_range['high']} (range: {asia_range['range']})"
        if asia_range.get("range") is not None else "N/A"
    )

    h1_close = float(h1_df["Close"].iloc[-1])
    h1_open = float(h1_df["Open"].iloc[-1])
    session_bias = "Bullish" if h1_close > h1_open else "Bearish"

    return {
        "current_session": current_session,
        "session_bias": session_bias,
        "volatility": characteristics["volatility"],
        "pattern": pattern,
        "bias_note": characteristics["bias_note"],
        "asia_range": asia_range_str,
        "session_ranges": ranges,
        "continuation_pct": continuation_pct,
    }
