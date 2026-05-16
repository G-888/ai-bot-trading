"""
strategies/smc.py — Smart Money Concepts (SMC) engine.

Detects: BOS, CHoCH, Order Blocks, Fair Value Gaps, Liquidity Sweeps.
All logic is pure Python. AI only explains the findings.
"""
import logging
import pandas as pd

from market.structure import (
    detect_bos,
    detect_choch,
    detect_order_blocks,
    detect_fair_value_gaps,
    detect_liquidity_sweeps,
    get_premium_discount,
    get_swing_points,
)
from market.indicators import current_rsi, get_last_n_swing_highs, get_last_n_swing_lows

logger = logging.getLogger(__name__)


def _structure_bias(df: pd.DataFrame, lookback: int = 3) -> str:
    """
    Determine structural bias from Higher Highs / Higher Lows (bullish)
    or Lower Highs / Lower Lows (bearish).
    """
    highs = get_last_n_swing_highs(df, n=4, lookback=lookback)
    lows = get_last_n_swing_lows(df, n=4, lookback=lookback)

    if len(highs) < 2 or len(lows) < 2:
        return "Neutral"

    hh = highs[-1][1] > highs[-2][1]
    hl = lows[-1][1] > lows[-2][1]
    lh = highs[-1][1] < highs[-2][1]
    ll = lows[-1][1] < lows[-2][1]

    if hh and hl:
        return "Bullish (HH + HL)"
    if lh and ll:
        return "Bearish (LH + LL)"
    if hh and ll:
        return "Mixed (HH + LL)"
    if lh and hl:
        return "Mixed (LH + HL)"
    return "Neutral"


def _find_key_ob(obs: list[dict], price: float) -> str:
    """Find the most relevant order block near current price."""
    if not obs:
        return "None detected"
    nearest = min(obs, key=lambda ob: abs(ob["mid"] - price))
    return f"{nearest['type']} at {nearest['bottom']}–{nearest['top']} (mid: {nearest['mid']})"


def _find_nearest_fvg(fvgs: list[dict], price: float) -> str:
    """Find the nearest unfilled FVG."""
    open_fvgs = [f for f in fvgs if f["bottom"] <= price <= f["top"] or abs(f["mid"] - price) < price * 0.005]
    if not open_fvgs:
        if fvgs:
            nearest = min(fvgs, key=lambda f: abs(f["mid"] - price))
            return f"{nearest['type']} at {nearest['bottom']}–{nearest['top']} (unmitigated)"
        return "None"
    nearest = min(open_fvgs, key=lambda f: abs(f["mid"] - price))
    return f"{nearest['type']} at {nearest['bottom']}–{nearest['top']} (price inside gap)"


def run_smc_analysis(df: pd.DataFrame, lookback: int = 3) -> dict:
    """
    Full SMC analysis pipeline.
    Returns structured dict with all detected SMC elements.
    """
    try:
        price = float(df["Close"].iloc[-1])

        structure_bias = _structure_bias(df, lookback)
        bos_list = detect_bos(df, lookback)
        choch_list = detect_choch(df, lookback)
        order_blocks = detect_order_blocks(df)
        fvg_list = detect_fair_value_gaps(df)
        sweeps = detect_liquidity_sweeps(df, lookback)
        swing_pts = get_swing_points(df, lookback)

        highs = swing_pts["highs"]
        lows = swing_pts["lows"]

        swing_high = highs[-1][1] if highs else price * 1.01
        swing_low = lows[-1][1] if lows else price * 0.99
        premium_discount = get_premium_discount(price, swing_high, swing_low)

        key_ob = _find_key_ob(order_blocks, price)
        nearest_fvg = _find_nearest_fvg(fvg_list, price)
        rsi_val = current_rsi(df, 14)

        liquidity_direction = "Neutral"
        if sweeps:
            last_sweep = sweeps[-1]
            if last_sweep["type"] == "Bullish Sweep":
                liquidity_direction = "Bullish (stop hunt below completed — demand likely)"
            else:
                liquidity_direction = "Bearish (stop hunt above completed — supply likely)"

        overall_bias = "Neutral"
        bull_signals = 0
        bear_signals = 0

        if "Bullish" in structure_bias:
            bull_signals += 2
        elif "Bearish" in structure_bias:
            bear_signals += 2

        for b in bos_list:
            if b["direction"] == "Bullish":
                bull_signals += 1
            else:
                bear_signals += 1

        for b in choch_list:
            if b["direction"] == "Bullish":
                bull_signals += 2
            else:
                bear_signals += 2

        if "Bullish" in liquidity_direction:
            bull_signals += 1
        elif "Bearish" in liquidity_direction:
            bear_signals += 1

        if bull_signals > bear_signals:
            overall_bias = "Bullish"
        elif bear_signals > bull_signals:
            overall_bias = "Bearish"

        return {
            "price": price,
            "structure_bias": structure_bias,
            "overall_bias": overall_bias,
            "bos_list": bos_list,
            "bos_count": len(bos_list),
            "choch_list": choch_list,
            "choch_count": len(choch_list),
            "order_blocks": order_blocks,
            "key_ob_level": key_ob,
            "fvg_list": fvg_list,
            "nearest_fvg": nearest_fvg,
            "sweeps": sweeps,
            "sweep_count": len(sweeps),
            "liquidity_direction": liquidity_direction,
            "premium_discount": premium_discount,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "rsi": rsi_val,
        }
    except Exception as e:
        logger.error("SMC analysis failed: %s", e)
        return {
            "price": 0,
            "structure_bias": "Error",
            "overall_bias": "Neutral",
            "bos_list": [], "bos_count": 0,
            "choch_list": [], "choch_count": 0,
            "order_blocks": [], "key_ob_level": "N/A",
            "fvg_list": [], "nearest_fvg": "N/A",
            "sweeps": [], "sweep_count": 0,
            "liquidity_direction": "Unknown",
            "premium_discount": "Unknown",
            "swing_high": 0, "swing_low": 0, "rsi": 50,
        }


def format_smc_text(smc: dict) -> str:
    """Format SMC analysis as a clean Telegram message."""
    bos_lines = []
    for b in smc.get("bos_list", []):
        bos_lines.append(f"  {b['direction']} {b['type']} at {b['level']}")

    choch_lines = []
    for c in smc.get("choch_list", []):
        choch_lines.append(f"  {c.get('note', c['direction'] + ' CHoCH')} at {c['level']}")

    obs = smc.get("order_blocks", [])
    ob_lines = [f"  {ob['type']}: {ob['bottom']}–{ob['top']}" for ob in obs[-3:]]

    fvgs = smc.get("fvg_list", [])
    fvg_lines = [f"  {f['type']}: {f['bottom']}–{f['top']}" for f in fvgs[-3:]]

    bias_emoji = "▲" if smc.get("overall_bias") == "Bullish" else ("▼" if smc.get("overall_bias") == "Bearish" else "◆")

    return (
        f"XAUUSD — Smart Money Concepts\n\n"
        f"Price: {smc['price']}\n"
        f"Structure: {smc['structure_bias']}\n"
        f"Overall Bias: {bias_emoji} {smc['overall_bias']}\n"
        f"Premium/Discount: {smc['premium_discount']}\n"
        f"RSI: {smc['rsi']}\n\n"
        f"Break of Structure:\n" +
        ("\n".join(bos_lines) if bos_lines else "  None detected") + "\n\n"
        f"Change of Character:\n" +
        ("\n".join(choch_lines) if choch_lines else "  None detected") + "\n\n"
        f"Order Blocks (recent):\n" +
        ("\n".join(ob_lines) if ob_lines else "  None detected") + "\n\n"
        f"Fair Value Gaps:\n" +
        ("\n".join(fvg_lines) if fvg_lines else "  None detected") + "\n\n"
        f"Liquidity: {smc['liquidity_direction']}\n"
        f"Nearest FVG: {smc['nearest_fvg']}\n"
        f"Key OB: {smc['key_ob_level']}"
    )
