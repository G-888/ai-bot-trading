"""
strategies/fibonacci.py — Full Fibonacci retracement and extension engine.

Python calculates all levels. AI only explains the setup.
"""
import logging
import pandas as pd
from market.indicators import get_last_n_swing_highs, get_last_n_swing_lows, current_rsi, atr

logger = logging.getLogger(__name__)

FIB_RATIOS = {
    "0.0 (Swing High/Low)": 0.0,
    "0.236": 0.236,
    "0.382": 0.382,
    "0.500": 0.500,
    "0.618": 0.618,
    "0.705": 0.705,
    "0.786": 0.786,
    "1.0 (Extension)": 1.0,
    "1.272 (Extension)": 1.272,
    "1.618 (Extension)": 1.618,
}

KEY_RATIOS = {
    "0.236": 0.236,
    "0.382": 0.382,
    "0.500": 0.500,
    "0.618": 0.618,
    "0.786": 0.786,
}


def auto_detect_swing(df: pd.DataFrame, lookback: int = 5) -> tuple[float, float, str] | None:
    """
    Auto-detect the most recent significant swing high and low.
    Returns (swing_high, swing_low, direction) or None.
    Direction = 'retracement_down' if last move was up (price near swing high)
                 'retracement_up'   if last move was down (price near swing low)
    """
    if len(df) < lookback * 3:
        return None

    highs = get_last_n_swing_highs(df, n=3, lookback=lookback)
    lows = get_last_n_swing_lows(df, n=3, lookback=lookback)

    if not highs or not lows:
        return None

    last_sh_idx, last_sh_price = highs[-1]
    last_sl_idx, last_sl_price = lows[-1]

    current_price = float(df["Close"].iloc[-1])

    if last_sh_price == last_sl_price:
        return None

    dist_from_high = abs(current_price - last_sh_price)
    dist_from_low = abs(current_price - last_sl_price)

    if dist_from_high < dist_from_low:
        direction = "retracement_down"
    else:
        direction = "retracement_up"

    swing_high = round(last_sh_price, 2)
    swing_low = round(last_sl_price, 2)

    if swing_high < swing_low:
        swing_high, swing_low = swing_low, swing_high

    return swing_high, swing_low, direction


def calculate_levels(swing_high: float, swing_low: float, direction: str) -> dict[str, float]:
    """
    Calculate key Fibonacci retracement levels.
    For retracement_down (was bullish): measure from low → high, levels are where price retraces.
    For retracement_up  (was bearish): measure from high → low.
    """
    range_size = swing_high - swing_low
    if range_size <= 0:
        return {}

    levels: dict[str, float] = {}

    if direction == "retracement_down":
        for name, ratio in KEY_RATIOS.items():
            levels[name] = round(swing_high - ratio * range_size, 2)
        levels["0.0 (Swing High)"] = swing_high
        levels["1.0 (Swing Low)"] = swing_low
        levels["1.272 Ext"] = round(swing_low - 0.272 * range_size, 2)
        levels["1.618 Ext"] = round(swing_low - 0.618 * range_size, 2)
    else:
        for name, ratio in KEY_RATIOS.items():
            levels[name] = round(swing_low + ratio * range_size, 2)
        levels["0.0 (Swing Low)"] = swing_low
        levels["1.0 (Swing High)"] = swing_high
        levels["1.272 Ext"] = round(swing_high + 0.272 * range_size, 2)
        levels["1.618 Ext"] = round(swing_high + 0.618 * range_size, 2)

    return levels


def find_nearest_level(price: float, levels: dict[str, float]) -> tuple[str, float]:
    """Find the Fibonacci level closest to the current price."""
    if not levels:
        return "N/A", price
    nearest_name = min(levels, key=lambda k: abs(levels[k] - price))
    return nearest_name, levels[nearest_name]


def score_confluence(
    price: float,
    levels: dict[str, float],
    df: pd.DataFrame,
    swing_high: float,
    swing_low: float,
) -> float:
    """
    Confluence score 0–100 based on:
    - Distance from key fib level (40 pts)
    - RSI alignment (20 pts)
    - ATR proximity (20 pts)
    - Swing size vs ATR (20 pts)
    """
    score = 0.0

    nearest_name, nearest_price = find_nearest_level(price, levels)
    if nearest_price:
        dist_pct = abs(price - nearest_price) / price * 100
        if dist_pct < 0.1:
            score += 40
        elif dist_pct < 0.3:
            score += 30
        elif dist_pct < 0.5:
            score += 20
        elif dist_pct < 1.0:
            score += 10

    rsi_val = current_rsi(df, 14)
    if nearest_name in ("0.382", "0.618"):
        if rsi_val < 35 or rsi_val > 65:
            score += 20
        elif rsi_val < 45 or rsi_val > 55:
            score += 10

    atr_val = float(atr(df, 14).iloc[-1]) if len(df) > 14 else 0
    if atr_val > 0:
        swing_size = swing_high - swing_low
        if swing_size > atr_val * 3:
            score += 20
        elif swing_size > atr_val * 1.5:
            score += 10

    if "0.618" in nearest_name or "0.382" in nearest_name:
        score += 10

    return round(min(score, 100), 1)


def run_fibonacci_analysis(df: pd.DataFrame, lookback: int = 5) -> dict | None:
    """
    Full Fibonacci analysis pipeline.
    Returns a structured result dict or None on failure.
    """
    try:
        swing = auto_detect_swing(df, lookback)
        if swing is None:
            return None

        swing_high, swing_low, direction = swing
        levels = calculate_levels(swing_high, swing_low, direction)

        if not levels:
            return None

        price = float(df["Close"].iloc[-1])
        nearest_name, nearest_price = find_nearest_level(price, levels)
        confluence = score_confluence(price, levels, df, swing_high, swing_low)
        rsi_val = current_rsi(df, 14)

        range_size = swing_high - swing_low

        if direction == "retracement_down":
            bias = "Bearish retracement in bullish swing"
            invalidation = round(swing_low - range_size * 0.05, 2)
            target = round(swing_high + range_size * 0.272, 2)
        else:
            bias = "Bullish retracement in bearish swing"
            invalidation = round(swing_high + range_size * 0.05, 2)
            target = round(swing_low - range_size * 0.272, 2)

        return {
            "swing_high": swing_high,
            "swing_low": swing_low,
            "direction": direction,
            "bias": bias,
            "levels": levels,
            "nearest_level": nearest_name,
            "nearest_price": nearest_price,
            "confluence_score": confluence,
            "invalidation": invalidation,
            "target": target,
            "rsi": rsi_val,
            "price": price,
            "range_size": round(range_size, 2),
        }
    except Exception as e:
        logger.error("Fibonacci analysis failed: %s", e)
        return None


def format_fib_text(fib: dict) -> str:
    """Format the Python-computed Fibonacci result as a clean Telegram message block."""
    levels = fib.get("levels", {})
    level_lines = "\n".join(
        f"  {name:20s} {price}"
        for name, price in sorted(levels.items(), key=lambda x: x[1], reverse=True)
    )

    conf = fib.get("confluence_score", 0)
    conf_bar = "█" * int(conf // 10) + "░" * (10 - int(conf // 10))

    arrow = "▼" if "down" in fib.get("direction", "") else "▲"

    return (
        f"XAUUSD — Fibonacci Analysis\n\n"
        f"Price: {fib['price']}\n"
        f"Swing High: {fib['swing_high']}\n"
        f"Swing Low:  {fib['swing_low']}\n"
        f"Direction:  {arrow} {fib['bias']}\n\n"
        f"Key Levels:\n{level_lines}\n\n"
        f"Nearest Level: {fib['nearest_level']} at {fib['nearest_price']}\n"
        f"RSI:           {fib['rsi']}\n\n"
        f"Confluence: [{conf_bar}] {conf:.0f}%\n\n"
        f"Invalidation: {fib['invalidation']}\n"
        f"Extension Target: {fib['target']}"
    )
