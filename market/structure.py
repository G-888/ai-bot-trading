"""
market/structure.py — Market structure analysis: swing points, BOS, CHoCH.

All logic is Python. No AI involvement.
"""
import pandas as pd
from market.indicators import get_last_n_swing_highs, get_last_n_swing_lows


def get_swing_points(df: pd.DataFrame, lookback: int = 3) -> dict:
    """Return recent swing highs and lows."""
    return {
        "highs": get_last_n_swing_highs(df, n=5, lookback=lookback),
        "lows": get_last_n_swing_lows(df, n=5, lookback=lookback),
    }


def detect_bos(df: pd.DataFrame, lookback: int = 3) -> list[dict]:
    """
    Detect Break of Structure (BOS).
    Bullish BOS: price closes above the last swing high.
    Bearish BOS: price closes below the last swing low.
    """
    from market.indicators import swing_highs, swing_lows
    results = []
    highs_mask = swing_highs(df["High"], lookback)
    lows_mask = swing_lows(df["Low"], lookback)

    swing_high_prices = df["High"][highs_mask].tolist()
    swing_low_prices = df["Low"][lows_mask].tolist()

    closes = df["Close"].tolist()
    if not swing_high_prices or not swing_low_prices:
        return results

    last_sh = swing_high_prices[-1]
    last_sl = swing_low_prices[-1]

    for i in range(len(closes) - 1, max(len(closes) - 10, 0), -1):
        c = closes[i]
        if c > last_sh:
            results.append({"type": "BOS", "direction": "Bullish", "level": round(last_sh, 2), "bar": i})
            break
        if c < last_sl:
            results.append({"type": "BOS", "direction": "Bearish", "level": round(last_sl, 2), "bar": i})
            break
    return results


def detect_choch(df: pd.DataFrame, lookback: int = 3) -> list[dict]:
    """
    Detect Change of Character (CHoCH).
    A CHoCH is the FIRST BOS against the prevailing trend.
    Simplified: detect if the most recent BOS is counter to the prior structural direction.
    """
    from market.indicators import swing_highs, swing_lows
    results = []
    highs_mask = swing_highs(df["High"], lookback)
    lows_mask = swing_lows(df["Low"], lookback)

    sh_prices = df["High"][highs_mask].tolist()
    sl_prices = df["Low"][lows_mask].tolist()
    if len(sh_prices) < 2 or len(sl_prices) < 2:
        return results

    hh = sh_prices[-1] > sh_prices[-2]
    hl = sl_prices[-1] > sl_prices[-2]
    lh = sh_prices[-1] < sh_prices[-2]
    ll = sl_prices[-1] < sl_prices[-2]

    if hh and hl:
        prior_trend = "Bullish"
    elif lh and ll:
        prior_trend = "Bearish"
    else:
        prior_trend = "Mixed"

    bos = detect_bos(df, lookback)
    for b in bos:
        if prior_trend == "Bullish" and b["direction"] == "Bearish":
            results.append({**b, "type": "CHoCH", "note": "Bearish CHoCH — potential trend reversal"})
        elif prior_trend == "Bearish" and b["direction"] == "Bullish":
            results.append({**b, "type": "CHoCH", "note": "Bullish CHoCH — potential trend reversal"})
    return results


def detect_order_blocks(df: pd.DataFrame, min_impulse_pct: float = 0.3) -> list[dict]:
    """
    Order Blocks (OBs):
    - Bullish OB: last bearish candle before a strong bullish impulse
    - Bearish OB: last bullish candle before a strong bearish impulse
    """
    obs = []
    closes = df["Close"].tolist()
    opens = df["Open"].tolist()
    highs = df["High"].tolist()
    lows = df["Low"].tolist()

    for i in range(2, len(df) - 2):
        candle_range = highs[i] - lows[i]
        if candle_range == 0:
            continue

        next_move = closes[i + 1] - closes[i]
        next_move_pct = abs(next_move) / closes[i] * 100

        if next_move_pct < min_impulse_pct:
            continue

        is_bearish_candle = closes[i] < opens[i]
        is_bullish_candle = closes[i] > opens[i]

        if is_bearish_candle and next_move > 0:
            obs.append({
                "type": "Bullish OB",
                "top": round(highs[i], 2),
                "bottom": round(lows[i], 2),
                "mid": round((highs[i] + lows[i]) / 2, 2),
                "bar_idx": i,
            })
        elif is_bullish_candle and next_move < 0:
            obs.append({
                "type": "Bearish OB",
                "top": round(highs[i], 2),
                "bottom": round(lows[i], 2),
                "mid": round((highs[i] + lows[i]) / 2, 2),
                "bar_idx": i,
            })

    return obs[-5:] if obs else []


def detect_fair_value_gaps(df: pd.DataFrame) -> list[dict]:
    """
    Fair Value Gaps (FVGs):
    - Bullish FVG: candle[i].low > candle[i-2].high  (gap up)
    - Bearish FVG: candle[i].high < candle[i-2].low  (gap down)
    """
    fvgs = []
    highs = df["High"].tolist()
    lows = df["Low"].tolist()

    for i in range(2, len(df)):
        bullish_gap = lows[i] > highs[i - 2]
        bearish_gap = highs[i] < lows[i - 2]

        if bullish_gap:
            fvgs.append({
                "type": "Bullish FVG",
                "top": round(lows[i], 2),
                "bottom": round(highs[i - 2], 2),
                "mid": round((lows[i] + highs[i - 2]) / 2, 2),
                "bar_idx": i,
            })
        elif bearish_gap:
            fvgs.append({
                "type": "Bearish FVG",
                "top": round(lows[i - 2], 2),
                "bottom": round(highs[i], 2),
                "mid": round((lows[i - 2] + highs[i]) / 2, 2),
                "bar_idx": i,
            })

    return fvgs[-5:] if fvgs else []


def detect_liquidity_sweeps(df: pd.DataFrame, lookback: int = 3) -> list[dict]:
    """
    Liquidity sweep: price briefly breaks a swing high/low but closes back inside.
    """
    from market.indicators import swing_highs, swing_lows
    sweeps = []
    highs_mask = swing_highs(df["High"], lookback)
    lows_mask = swing_lows(df["Low"], lookback)

    sh_levels = df["High"][highs_mask].tolist()
    sl_levels = df["Low"][lows_mask].tolist()

    highs = df["High"].tolist()
    lows = df["Low"].tolist()
    closes = df["Close"].tolist()

    for i in range(lookback, len(df)):
        for sh in sh_levels[-3:]:
            if highs[i] > sh and closes[i] < sh:
                sweeps.append({
                    "type": "Bearish Sweep",
                    "level": round(sh, 2),
                    "bar_idx": i,
                    "note": "Stop hunt above swing high",
                })
        for sl in sl_levels[-3:]:
            if lows[i] < sl and closes[i] > sl:
                sweeps.append({
                    "type": "Bullish Sweep",
                    "level": round(sl, 2),
                    "bar_idx": i,
                    "note": "Stop hunt below swing low",
                })

    return sweeps[-5:] if sweeps else []


def get_premium_discount(price: float, swing_high: float, swing_low: float) -> str:
    """Classify current price within the swing range."""
    if swing_high <= swing_low:
        return "Undefined"
    mid = (swing_high + swing_low) / 2
    equilibrium_band = (swing_high - swing_low) * 0.1
    if price > mid + equilibrium_band:
        pct = (price - swing_low) / (swing_high - swing_low) * 100
        return f"Premium ({pct:.0f}% of range)"
    if price < mid - equilibrium_band:
        pct = (price - swing_low) / (swing_high - swing_low) * 100
        return f"Discount ({pct:.0f}% of range)"
    return "Equilibrium"
