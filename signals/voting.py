"""
signals/voting.py — Strategy Voting Engine.

Combines outputs from all strategy engines into a weighted consensus vote.
Python computes all scores. AI only explains the final output.
"""
import logging
from datetime import datetime, timezone

import pandas as pd

from market.indicators import atr, rsi as rsi_indicator, ema
from market.regime import detect_regime, get_regime_vote_weights
from strategies.session import get_current_session

logger = logging.getLogger(__name__)

VOTE_BUY     = "BUY"
VOTE_SELL    = "SELL"
VOTE_NEUTRAL = "NEUTRAL"


# ── Individual strategy vote extractors ─────────────────────────────────────────

def _vote_smc(smc_result: dict | None) -> tuple[str, float]:
    """Extract SMC vote and confidence 0-1."""
    if not smc_result:
        return VOTE_NEUTRAL, 0.0
    bias = smc_result.get("overall_bias", "Neutral")
    choch = smc_result.get("choch_count", 0)
    bos   = smc_result.get("bos_count", 0)

    score = 0.0
    if choch > 0:
        score += 0.35
    if bos > 0:
        score += 0.20
    if len(smc_result.get("order_blocks", [])) > 0:
        score += 0.25
    if smc_result.get("sweep_count", 0) > 0:
        score += 0.20

    confidence = min(score, 1.0)

    if "Bullish" in bias:
        return VOTE_BUY, confidence
    if "Bearish" in bias:
        return VOTE_SELL, confidence
    return VOTE_NEUTRAL, confidence * 0.5


def _vote_fibonacci(fib_result: dict | None) -> tuple[str, float]:
    """Extract Fibonacci vote and confidence 0-1."""
    if not fib_result:
        return VOTE_NEUTRAL, 0.0
    conf_score = fib_result.get("confluence_score", 0) / 100.0
    direction  = fib_result.get("direction", "")
    nearest    = fib_result.get("nearest_level", "")
    rsi_val    = fib_result.get("rsi", 50)

    key_level_bonus = 0.15 if nearest in ("0.618", "0.382") else 0.0
    rsi_bonus = 0.10 if (rsi_val < 35 or rsi_val > 65) else 0.0
    confidence = min(conf_score + key_level_bonus + rsi_bonus, 1.0)

    if "retracement_up" in direction:
        return VOTE_BUY, confidence
    if "retracement_down" in direction:
        return VOTE_SELL, confidence
    return VOTE_NEUTRAL, confidence * 0.5


def _vote_momentum(df: pd.DataFrame) -> tuple[str, float]:
    """Compute momentum vote from EMA crossover + RSI."""
    try:
        if len(df) < 25:
            return VOTE_NEUTRAL, 0.0

        closes = df["Close"]
        ema_fast = ema(closes, 9)
        ema_slow = ema(closes, 21)
        rsi_s    = rsi_indicator(closes, 14)

        fast_now  = float(ema_fast.iloc[-1])
        slow_now  = float(ema_slow.iloc[-1])
        fast_prev = float(ema_fast.iloc[-2])
        slow_prev = float(ema_slow.iloc[-2])
        rsi_now   = float(rsi_s.iloc[-1])

        gap_now  = fast_now - slow_now
        gap_prev = fast_prev - slow_prev

        bullish_cross  = gap_prev <= 0 and gap_now > 0
        bearish_cross  = gap_prev >= 0 and gap_now < 0
        bullish_trend  = gap_now > 0
        bearish_trend  = gap_now < 0

        rsi_bull  = rsi_now > 55
        rsi_bear  = rsi_now < 45
        rsi_extr  = rsi_now > 70 or rsi_now < 30

        score = 0.0
        if bullish_cross or bearish_cross:
            score += 0.40
        elif bullish_trend or bearish_trend:
            score += 0.20

        if rsi_extr:
            score += 0.30
        elif rsi_bull or rsi_bear:
            score += 0.15

        atr_s   = atr(df, 14)
        avg_atr = float(atr_s.tail(20).mean()) if len(atr_s) >= 20 else 0.0
        cur_atr = float(atr_s.iloc[-1])
        if avg_atr > 0 and cur_atr > avg_atr * 1.2:
            score += 0.20

        confidence = min(score, 1.0)

        if bullish_trend and (rsi_bull or bullish_cross):
            return VOTE_BUY, confidence
        if bearish_trend and (rsi_bear or bearish_cross):
            return VOTE_SELL, confidence
        return VOTE_NEUTRAL, confidence * 0.5

    except Exception as e:
        logger.error("Momentum vote failed: %s", e)
        return VOTE_NEUTRAL, 0.0


def _vote_session(session_data: dict | None) -> tuple[str, float]:
    """Extract session vote."""
    if not session_data:
        return VOTE_NEUTRAL, 0.3
    bias = session_data.get("session_bias", "")
    pattern = session_data.get("pattern", "")
    cont_pct = session_data.get("continuation_pct", 50) / 100.0
    session  = session_data.get("current_session", "")

    quality_bonus = 0.20 if session in ("London", "London/NY Overlap") else 0.0
    if "Bullish" in bias:
        vote = VOTE_BUY
    elif "Bearish" in bias:
        vote = VOTE_SELL
    else:
        vote = VOTE_NEUTRAL

    if "Reversal" in pattern or "Sweep" in pattern:
        if vote == VOTE_BUY:
            vote = VOTE_SELL
        elif vote == VOTE_SELL:
            vote = VOTE_BUY

    confidence = min(cont_pct * 0.8 + quality_bonus, 1.0)
    return vote, confidence


def _vote_confluence(confluence_result: dict | None) -> tuple[str, float]:
    """Extract confluence engine vote."""
    if not confluence_result:
        return VOTE_NEUTRAL, 0.0
    total     = confluence_result.get("total", 0) / 100.0
    direction = confluence_result.get("direction", "")
    strength  = confluence_result.get("signal_strength", "NO SIGNAL")

    strength_map = {"STRONG": 1.0, "MODERATE": 0.75, "WEAK": 0.45, "NO SIGNAL": 0.0}
    quality = strength_map.get(strength, 0.0)
    confidence = min(total * 0.6 + quality * 0.4, 1.0)

    if direction == "BUY":
        return VOTE_BUY, confidence
    if direction == "SELL":
        return VOTE_SELL, confidence
    return VOTE_NEUTRAL, confidence * 0.5


# ── Session overlap boost ────────────────────────────────────────────────────────

def _session_weight_boost(weights: dict) -> dict:
    """During London/NY overlap, increase session weight by 50% of its value."""
    session = get_current_session()
    if session == "London/NY Overlap":
        extra = weights["session"] * 0.50
        weights = dict(weights)
        weights["session"] = min(weights["session"] + extra, 1.0)
        total = sum(weights.values())
        weights = {k: round(v / total, 4) for k, v in weights.items()}
    return weights


# ── Volatility-aware weight dampening ──────────────────────────────────────────

def _volatility_weight_adjust(weights: dict, regime: dict) -> dict:
    """During high volatility, dampen momentum and boost session/confluence."""
    vol = regime.get("volatility_score", 0.5)
    if vol > 0.80:
        weights = dict(weights)
        shift = 0.05
        weights["momentum"]   = max(weights["momentum"]   - shift, 0.05)
        weights["session"]    = min(weights["session"]    + shift * 0.5, 0.40)
        weights["confluence"] = min(weights["confluence"] + shift * 0.5, 0.40)
        total = sum(weights.values())
        weights = {k: round(v / total, 4) for k, v in weights.items()}
    return weights


# ── Main voting engine ───────────────────────────────────────────────────────────

def run_vote(
    df: pd.DataFrame,
    smc_result:        dict | None = None,
    fib_result:        dict | None = None,
    session_data:      dict | None = None,
    confluence_result: dict | None = None,
) -> dict:
    """
    Run all strategy votes and return weighted consensus.

    Returns:
        votes: dict of strategy → {vote, confidence}
        weights: dict of strategy → weight
        final_bias: BUY | SELL | NEUTRAL
        agreement_count: int — how many strategies agree with final
        agreement_total: int — total strategies with a real vote
        confidence_pct: float — 0-100
        regime: dict — current market regime
        suppressed: bool
        suppress_reason: str
    """
    try:
        regime = detect_regime(df)
        raw_weights = get_regime_vote_weights(regime["regime"])
        raw_weights = _session_weight_boost(raw_weights)
        raw_weights = _volatility_weight_adjust(raw_weights, regime)

        smc_vote,  smc_conf  = _vote_smc(smc_result)
        fib_vote,  fib_conf  = _vote_fibonacci(fib_result)
        mom_vote,  mom_conf  = _vote_momentum(df)
        sess_vote, sess_conf = _vote_session(session_data)
        conf_vote, conf_conf = _vote_confluence(confluence_result)

        votes = {
            "SMC":        {"vote": smc_vote,  "confidence": round(smc_conf  * 100, 1)},
            "Fibonacci":  {"vote": fib_vote,  "confidence": round(fib_conf  * 100, 1)},
            "Momentum":   {"vote": mom_vote,  "confidence": round(mom_conf  * 100, 1)},
            "Session":    {"vote": sess_vote, "confidence": round(sess_conf * 100, 1)},
            "Confluence": {"vote": conf_vote, "confidence": round(conf_conf * 100, 1)},
        }

        strategy_map = {
            "SMC":        (smc_vote,  smc_conf,  raw_weights["smc"]),
            "Fibonacci":  (fib_vote,  fib_conf,  raw_weights["fibonacci"]),
            "Momentum":   (mom_vote,  mom_conf,  raw_weights["momentum"]),
            "Session":    (sess_vote, sess_conf, raw_weights["session"]),
            "Confluence": (conf_vote, conf_conf, raw_weights["confluence"]),
        }

        buy_score  = 0.0
        sell_score = 0.0
        for _name, (vote, conf, wt) in strategy_map.items():
            if vote == VOTE_BUY:
                buy_score  += wt * conf
            elif vote == VOTE_SELL:
                sell_score += wt * conf

        total_score = buy_score + sell_score
        if total_score < 0.05:
            final_bias  = VOTE_NEUTRAL
            confidence  = 0.0
        elif buy_score > sell_score:
            final_bias  = VOTE_BUY
            confidence  = buy_score / max(total_score, 0.001)
        else:
            final_bias  = VOTE_SELL
            confidence  = sell_score / max(total_score, 0.001)

        agreement_count = sum(
            1 for _name, (vote, _c, _w) in strategy_map.items()
            if vote == final_bias and vote != VOTE_NEUTRAL
        )
        real_votes = sum(
            1 for _name, (vote, _c, _w) in strategy_map.items()
            if vote != VOTE_NEUTRAL
        )

        conflict_ratio = 0.0 if real_votes == 0 else (real_votes - agreement_count) / real_votes

        from market.regime import should_suppress_signal
        suppressed, suppress_reason = should_suppress_signal(
            regime, confidence * 100, conflict_ratio
        )

        return {
            "votes":             votes,
            "weights":           raw_weights,
            "final_bias":        final_bias,
            "agreement_count":   agreement_count,
            "agreement_total":   real_votes,
            "confidence_pct":    round(confidence * 100, 1),
            "buy_score":         round(buy_score, 4),
            "sell_score":        round(sell_score, 4),
            "conflict_ratio":    round(conflict_ratio, 3),
            "regime":            regime,
            "suppressed":        suppressed,
            "suppress_reason":   suppress_reason,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Voting engine failed: %s", e)
        return {
            "votes":           {},
            "weights":         {},
            "final_bias":      VOTE_NEUTRAL,
            "agreement_count": 0,
            "agreement_total": 0,
            "confidence_pct":  0.0,
            "buy_score":       0.0,
            "sell_score":      0.0,
            "conflict_ratio":  1.0,
            "regime":          {"regime": "UNKNOWN", "label": "Unknown"},
            "suppressed":      True,
            "suppress_reason": f"Engine error: {e}",
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }


def format_vote_text(result: dict) -> str:
    """Format voting result as a clean Telegram message."""
    votes    = result.get("votes", {})
    weights  = result.get("weights", {})
    bias     = result.get("final_bias", "NEUTRAL")
    agree    = result.get("agreement_count", 0)
    total    = result.get("agreement_total", 0)
    conf_pct = result.get("confidence_pct", 0.0)
    regime   = result.get("regime", {})
    suppressed = result.get("suppressed", False)
    reason   = result.get("suppress_reason", "")

    bias_arrow = {"BUY": "▲", "SELL": "▼", "NEUTRAL": "◆"}.get(bias, "◆")
    conf_bar   = "█" * int(conf_pct // 10) + "░" * (10 - int(conf_pct // 10))

    weight_key = {
        "SMC": "smc", "Fibonacci": "fibonacci",
        "Momentum": "momentum", "Session": "session", "Confluence": "confluence",
    }

    lines = ["XAUUSD — Strategy Votes\n"]
    lines.append(f"Regime: {regime.get('label', 'Unknown')}\n")

    for name, data in votes.items():
        v    = data["vote"]
        c    = data["confidence"]
        wt   = weights.get(weight_key.get(name, ""), 0.0)
        icon = {"BUY": "▲", "SELL": "▼", "NEUTRAL": "◆"}.get(v, "◆")
        lines.append(f"{name:<12} {icon} {v:<8} {c:4.0f}%  (wt {wt:.0%})")

    lines.append(f"\nFinal Bias:   {bias_arrow} {bias}")
    lines.append(f"Agreement:    {agree}/{total if total > 0 else len(votes)} strategies aligned")
    lines.append(f"Confidence:   [{conf_bar}] {conf_pct:.0f}%")

    if suppressed:
        lines.append(f"\nSignal Suppressed: {reason}")

    return "\n".join(lines)
