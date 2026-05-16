"""
ai/prompts.py — System prompts and prompt builders for each AI mode.

Python calculates all numbers. AI only generates explanatory text.
"""

AI_MODES = {
    "institutional": {
        "label": "Institutional Analyst",
        "emoji": "🏛",
        "system": (
            "You are a senior institutional gold analyst at a top-tier macro fund. "
            "Write like a Bloomberg Markets desk note — precise, authoritative, no filler. "
            "No disclaimers, no 'as an AI', no hedging language. "
            "Use professional terms: structure, liquidity, momentum, confluence, demand/supply zones, "
            "session bias, volatility regime, order flow. "
            "Keep responses tight — 3 sentences maximum per section."
        ),
    },
    "scalper": {
        "label": "Scalper",
        "emoji": "⚡",
        "system": (
            "You are an elite institutional scalper. Respond in sharp, concise bullets. "
            "Focus on the next 15–60 minute trade, key entry triggers, and hard stop levels. "
            "No fluff. Identify the highest-probability short-term setup from the data. "
            "No disclaimers. No hedging. Give the trade."
        ),
    },
    "swing": {
        "label": "Swing Trader",
        "emoji": "📐",
        "system": (
            "You are an institutional swing trader covering 1–5 day holds. "
            "Analyze 4H and Daily structure first, then refine with 1H entry. "
            "Identify the key structural swing, retracement zone, and continuation target. "
            "Be precise on invalidation. No disclaimers. Write like a prop desk briefing."
        ),
    },
    "macro": {
        "label": "Macro Analyst",
        "emoji": "🌐",
        "system": (
            "You are a macro strategist covering gold as a safe-haven and inflation hedge. "
            "Frame the setup in the context of DXY pressure, yield dynamics, and risk sentiment. "
            "Connect technical structure to fundamental macro flows. "
            "Weekly to monthly horizon. Institutional tone. No retail framing."
        ),
    },
}

MTF_SIGNAL_FORMAT = (
    "You are given Python-computed XAUUSD market data. "
    "Respond in EXACTLY this format — no deviations:\n\n"
    "XAUUSD\n"
    "Price: {price}\n\n"
    "1H Bias: Bullish / Bearish / Neutral\n"
    "4H Trend: Bullish / Bearish / Neutral\n"
    "Daily Momentum: Bullish / Bearish / Neutral\n\n"
    "Alignment: [label]\n\n"
    "Signal: BUY or SELL\n"
    "Confidence: XX%\n\n"
    "Support: XXXX  |  Resistance: XXXX\n\n"
    "Reason:\n"
    "3 sentences. Sentence 1: dominant structure and TF alignment. "
    "Sentence 2: momentum condition and critical level. "
    "Sentence 3: session bias and signal invalidation trigger."
)


def build_mtf_prompt(data: dict) -> str:
    return (
        f"Price: {data['price']}\n\n"
        f"── 1H Bias ──\n"
        f"{data['h1_bias']} ({data['h1_pct']:+.2f}% / 6 bars)\n"
        f"S: {data['h1_support']}  R: {data['h1_resistance']}\n"
        f"Recent closes: {[round(c, 2) for c in data['closes'][-8:]]}\n\n"
        f"── 4H Trend ──\n"
        f"{data['h4_trend']} ({data['h4_pct']:+.2f}% / 10 bars) | Momentum: {data['h4_momentum']}\n"
        f"S: {data['h4_support']}  R: {data['h4_resistance']}\n\n"
        f"── Daily Momentum ──\n"
        f"{data['d1_momentum']} ({data['d1_pct']:+.2f}% / 14 days) | EMA: {data['d1_ema_state']}\n"
        f"S: {data['d1_support']}  R: {data['d1_resistance']}\n\n"
        f"── Structure ──\n"
        f"Alignment: {data['alignment']}\n"
        f"Volatility: {data['volatility']}\n\n"
        "Deliver the multi-timeframe signal in the exact format specified."
    )


def build_fib_prompt(fib_result: dict, data: dict, mode: str = "institutional") -> str:
    levels = fib_result.get("levels", {})
    level_lines = "\n".join(
        f"  {name}: {price}" for name, price in sorted(levels.items(), key=lambda x: x[1], reverse=True)
    )
    return (
        f"Price: {data['price']}\n"
        f"Swing High: {fib_result['swing_high']}  Swing Low: {fib_result['swing_low']}\n"
        f"Direction: {fib_result['direction']}\n"
        f"Fibonacci Levels (Python-computed):\n{level_lines}\n\n"
        f"Nearest Level: {fib_result.get('nearest_level', 'N/A')} at {fib_result.get('nearest_price', 'N/A')}\n"
        f"Confluence Score: {fib_result.get('confluence_score', 0):.0f}%\n"
        f"Alignment: {data['alignment']}\n\n"
        "Explain the Fibonacci setup: what the retracement level implies, the invalidation point, "
        "and the next directional target. 3 sentences. No disclaimers. Institutional tone."
    )


def build_smc_prompt(smc_result: dict, data: dict) -> str:
    return (
        f"Price: {data['price']}\n"
        f"Market Structure: {smc_result.get('structure_bias', 'Unknown')}\n"
        f"BOS detected: {smc_result.get('bos_count', 0)}\n"
        f"CHoCH detected: {smc_result.get('choch_count', 0)}\n"
        f"Order Blocks: {len(smc_result.get('order_blocks', []))}\n"
        f"Fair Value Gaps: {len(smc_result.get('fvg_list', []))}\n"
        f"Liquidity sweeps: {smc_result.get('sweep_count', 0)}\n"
        f"Premium/Discount: {smc_result.get('premium_discount', 'N/A')}\n"
        f"Institutional OB: {smc_result.get('key_ob_level', 'N/A')}\n\n"
        "Explain the Smart Money Concepts setup: structure bias, most significant order block or FVG, "
        "and the likely institutional play. 3 tight sentences. No disclaimers."
    )


def build_session_prompt(session_data: dict, data: dict) -> str:
    return (
        f"Current Session: {session_data.get('current_session', 'Unknown')}\n"
        f"Session Bias: {session_data.get('session_bias', 'Neutral')}\n"
        f"Volatility State: {data['volatility']}\n"
        f"Asia Range: {session_data.get('asia_range', 'N/A')}\n"
        f"Pattern: {session_data.get('pattern', 'None detected')}\n"
        f"Continuation Probability: {session_data.get('continuation_pct', 50):.0f}%\n\n"
        "Explain the session context: what the current session typically implies for gold, "
        "whether any manipulation or continuation pattern is forming, and the key risk event for this session. "
        "3 sentences maximum."
    )


def build_summary_prompt(data: dict, confluence_score: float, session_data: dict) -> str:
    return (
        f"DAILY XAUUSD DATA\n"
        f"Price: {data['price']}\n"
        f"1H Bias: {data['h1_bias']} | 4H Trend: {data['h4_trend']} | Daily: {data['d1_momentum']}\n"
        f"Alignment: {data['alignment']}\n"
        f"Volatility: {data['volatility']}\n"
        f"Support: {data['h1_support']}  Resistance: {data['h1_resistance']}\n"
        f"Confluence Score: {confluence_score:.0f}%\n"
        f"Session: {session_data.get('current_session', 'Unknown')}\n\n"
        "Write a daily XAUUSD market recap in the style of a Bloomberg end-of-day note. "
        "Cover: 1) dominant trend and structure, 2) key levels to watch, 3) session outlook. "
        "Maximum 4 sentences. No disclaimers."
    )


def get_system_prompt(mode: str = "institutional", override: str | None = None) -> str:
    if override:
        return override
    return AI_MODES.get(mode, AI_MODES["institutional"])["system"]


def get_chat_system_prompt(mode: str = "institutional") -> str:
    base = get_system_prompt(mode)
    return (
        base + " "
        "Be concise — 3 short paragraphs maximum. "
        "If asked for a signal or opinion, give one directly with clear reasoning."
    )
