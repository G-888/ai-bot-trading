"""
signals/confluence.py — Multi-factor confluence scoring engine.

Python calculates everything. Score comes from indicator math, not AI guessing.

Scoring factors (total 100 pts):
  TF Alignment     25 pts
  SMC Structure    20 pts
  Fibonacci        15 pts
  RSI              15 pts
  Session          15 pts
  Volatility        10 pts
"""
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def score_tf_alignment(gold_data: dict) -> tuple[float, str]:
    """
    25 pts max.
    Full alignment = 25, partial = 15, one = 8, conflicting = 0.
    """
    biases = [gold_data.get("h1_bias"), gold_data.get("h4_trend"), gold_data.get("d1_momentum")]
    bull = biases.count("Bullish")
    bear = biases.count("Bearish")

    if bull == 3 or bear == 3:
        return 25.0, "Full alignment"
    if bull == 2 or bear == 2:
        return 15.0, "Partial alignment"
    if bull == 1 or bear == 1:
        return 8.0, "Weak alignment"
    return 0.0, "Conflicting structure"


def score_smc(smc_result: dict | None) -> tuple[float, str]:
    """
    20 pts max.
    Points for BOS, CHoCH, OBs, FVGs, and sweep confirmation.
    """
    if smc_result is None:
        return 0.0, "No SMC data"

    pts = 0.0
    notes = []

    if smc_result.get("choch_count", 0) > 0:
        pts += 8
        notes.append("CHoCH")
    if smc_result.get("bos_count", 0) > 0:
        pts += 5
        notes.append("BOS")
    if len(smc_result.get("order_blocks", [])) > 0:
        pts += 4
        notes.append("OB")
    if len(smc_result.get("fvg_list", [])) > 0:
        pts += 2
        notes.append("FVG")
    if smc_result.get("sweep_count", 0) > 0:
        pts += 1
        notes.append("Sweep")

    return min(pts, 20.0), " + ".join(notes) if notes else "None"


def score_fibonacci(fib_result: dict | None) -> tuple[float, str]:
    """
    15 pts max based on proximity to key fib level and confluence score.
    """
    if fib_result is None:
        return 0.0, "No Fibonacci data"

    fib_conf = fib_result.get("confluence_score", 0)
    nearest = fib_result.get("nearest_level", "")

    pts = fib_conf * 0.15

    if nearest in ("0.382", "0.618"):
        pts = min(pts + 3, 15)
    elif nearest in ("0.500", "0.786"):
        pts = min(pts + 1, 15)

    note = f"Near {nearest}" if nearest else "N/A"
    return round(min(pts, 15.0), 1), note


def score_rsi(df: pd.DataFrame) -> tuple[float, str]:
    """
    15 pts max.
    Extreme RSI (oversold/overbought) + momentum alignment.
    """
    from market.indicators import current_rsi
    rsi_val = current_rsi(df, 14)

    if rsi_val < 30:
        return 15.0, f"Oversold RSI {rsi_val}"
    if rsi_val > 70:
        return 15.0, f"Overbought RSI {rsi_val}"
    if rsi_val < 40:
        return 10.0, f"Bearish RSI {rsi_val}"
    if rsi_val > 60:
        return 10.0, f"Bullish RSI {rsi_val}"
    if rsi_val < 45 or rsi_val > 55:
        return 5.0, f"Neutral RSI {rsi_val}"
    return 0.0, f"Mid RSI {rsi_val}"


def score_session(session_data: dict | None) -> tuple[float, str]:
    """
    15 pts max.
    High-volume sessions and continuation patterns score highest.
    """
    if session_data is None:
        return 5.0, "No session data"

    session = session_data.get("current_session", "Unknown")
    pattern = session_data.get("pattern", "")
    cont_pct = session_data.get("continuation_pct", 50)

    pts = 0.0

    if session in ("London", "London/NY Overlap"):
        pts += 8
    elif session == "New York":
        pts += 6
    elif session == "Asia":
        pts += 3
    else:
        pts += 0

    if "Continuation" in pattern or "Breakout" in pattern:
        pts += 5
    elif "Sweep" in pattern:
        pts += 3
    elif "Compression" in pattern:
        pts += 1

    if cont_pct > 70:
        pts += 2

    note = f"{session} / {pattern[:30]}" if pattern else session
    return round(min(pts, 15.0), 1), note


def score_volatility(gold_data: dict) -> tuple[float, str]:
    """
    10 pts max.
    Medium volatility is ideal for trend entries. Low = neutral. High = cautious.
    """
    vol = gold_data.get("volatility", "Unknown")
    if vol == "Medium":
        return 10.0, "Medium — optimal"
    if vol == "High":
        return 5.0, "High — extended"
    if vol == "Low":
        return 3.0, "Low — compressing"
    return 0.0, "Unknown"


def calculate_confluence(
    gold_data: dict,
    df: pd.DataFrame,
    smc_result: dict | None = None,
    fib_result: dict | None = None,
    session_data: dict | None = None,
) -> dict:
    """
    Calculate the total confluence score and return a breakdown.
    """
    tf_pts, tf_note = score_tf_alignment(gold_data)
    smc_pts, smc_note = score_smc(smc_result)
    fib_pts, fib_note = score_fibonacci(fib_result)
    rsi_pts, rsi_note = score_rsi(df)
    sess_pts, sess_note = score_session(session_data)
    vol_pts, vol_note = score_volatility(gold_data)

    total = tf_pts + smc_pts + fib_pts + rsi_pts + sess_pts + vol_pts

    if total >= 75:
        signal_strength = "STRONG"
    elif total >= 55:
        signal_strength = "MODERATE"
    elif total >= 35:
        signal_strength = "WEAK"
    else:
        signal_strength = "NO SIGNAL"

    biases = [gold_data.get("h1_bias"), gold_data.get("h4_trend"), gold_data.get("d1_momentum")]
    bull = biases.count("Bullish")
    bear = biases.count("Bearish")
    direction = "BUY" if bull >= bear else "SELL"

    return {
        "total": round(total, 1),
        "signal_strength": signal_strength,
        "direction": direction,
        "breakdown": {
            "TF Alignment": (tf_pts, tf_note),
            "SMC": (smc_pts, smc_note),
            "Fibonacci": (fib_pts, fib_note),
            "RSI": (rsi_pts, rsi_note),
            "Session": (sess_pts, sess_note),
            "Volatility": (vol_pts, vol_note),
        },
    }


def format_confluence_text(result: dict) -> str:
    """Format confluence score as a clean Telegram message."""
    total = result["total"]
    bar = "█" * int(total // 10) + "░" * (10 - int(total // 10))
    bd = result["breakdown"]

    lines = [
        f"XAUUSD — Confluence Score\n",
        f"[{bar}] {total:.0f}/100\n",
        f"Signal: {result['direction']}  ({result['signal_strength']})\n",
        f"\nBreakdown:",
    ]
    for factor, (pts, note) in bd.items():
        lines.append(f"  {factor:15s} {pts:4.1f}  {note}")

    return "\n".join(lines)
