"""
market/indicators.py — Pure Python/pandas technical indicator calculations.

All values are computed here. AI receives computed results only.
"""
import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, period)
    std = series.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def swing_highs(series: pd.Series, lookback: int = 5) -> pd.Series:
    """Return a boolean Series marking swing highs."""
    result = pd.Series(False, index=series.index)
    for i in range(lookback, len(series) - lookback):
        window = series.iloc[i - lookback: i + lookback + 1]
        if series.iloc[i] == window.max():
            result.iloc[i] = True
    return result


def swing_lows(series: pd.Series, lookback: int = 5) -> pd.Series:
    """Return a boolean Series marking swing lows."""
    result = pd.Series(False, index=series.index)
    for i in range(lookback, len(series) - lookback):
        window = series.iloc[i - lookback: i + lookback + 1]
        if series.iloc[i] == window.min():
            result.iloc[i] = True
    return result


def get_last_n_swing_highs(df: pd.DataFrame, n: int = 3, lookback: int = 3) -> list[tuple]:
    """Return last n swing high (index, price) pairs."""
    highs = swing_highs(df["High"], lookback)
    hits = df["High"][highs]
    result = [(idx, round(float(price), 2)) for idx, price in hits.items()]
    return result[-n:]


def get_last_n_swing_lows(df: pd.DataFrame, n: int = 3, lookback: int = 3) -> list[tuple]:
    """Return last n swing low (index, price) pairs."""
    lows = swing_lows(df["Low"], lookback)
    hits = df["Low"][lows]
    result = [(idx, round(float(price), 2)) for idx, price in hits.items()]
    return result[-n:]


def current_rsi(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 50.0
    return round(float(rsi(df["Close"], period).iloc[-1]), 1)


def current_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    return round(float(atr(df, period).iloc[-1]), 2)


def price_vs_ema(df: pd.DataFrame, period: int = 50) -> str:
    if len(df) < period:
        return "Unknown"
    e = ema(df["Close"], period)
    price = float(df["Close"].iloc[-1])
    ema_val = float(e.iloc[-1])
    if price > ema_val * 1.001:
        return "Above"
    if price < ema_val * 0.999:
        return "Below"
    return "At"
