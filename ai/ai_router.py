"""
ai/ai_router.py — AI provider routing with fallback support.

Priority: Groq → (future: OpenRouter → Gemini → Ollama)
"""
import logging
import os
import time
from functools import lru_cache

from groq import Groq

from ai.prompts import get_system_prompt, get_chat_system_prompt, AI_MODES

logger = logging.getLogger(__name__)

_groq_client: Groq | None = None

_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 120  # seconds


def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def _cache_key(*args) -> str:
    return "|".join(str(a)[:80] for a in args)


def _from_cache(key: str) -> str | None:
    if key in _CACHE:
        text, ts = _CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return text
        del _CACHE[key]
    return None


def _to_cache(key: str, text: str) -> None:
    _CACHE[key] = (text, time.time())
    if len(_CACHE) > 50:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][1])
        del _CACHE[oldest]


def call_groq(
    user_prompt: str,
    system_prompt: str,
    model: str = "llama-3.3-70b-versatile",
    max_tokens: int = 350,
    temperature: float = 0.4,
    use_cache: bool = False,
) -> str:
    """Call Groq with retry logic."""
    if use_cache:
        key = _cache_key(system_prompt[:60], user_prompt[:80])
        cached = _from_cache(key)
        if cached:
            logger.debug("AI cache hit")
            return cached

    groq = _get_groq()
    last_exc = None

    for attempt in range(3):
        try:
            resp = groq.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = resp.choices[0].message.content
            if use_cache:
                key = _cache_key(system_prompt[:60], user_prompt[:80])
                _to_cache(key, text)
            return text
        except Exception as e:
            last_exc = e
            logger.warning("Groq attempt %d failed: %s", attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))

    logger.error("All Groq attempts failed: %s", last_exc)
    return "AI analysis temporarily unavailable. Please try again."


def generate_signal(user_prompt: str, mode: str = "institutional") -> str:
    """Generate a structured trading signal."""
    from ai.prompts import MTF_SIGNAL_FORMAT
    system = get_system_prompt(mode) + "\n\n" + MTF_SIGNAL_FORMAT
    return call_groq(user_prompt, system, max_tokens=350, use_cache=False)


def generate_fib_commentary(user_prompt: str, mode: str = "institutional") -> str:
    """Generate Fibonacci setup commentary."""
    system = get_system_prompt(mode)
    return call_groq(user_prompt, system, max_tokens=250, use_cache=False)


def generate_smc_commentary(user_prompt: str, mode: str = "institutional") -> str:
    """Generate SMC analysis commentary."""
    system = get_system_prompt(mode)
    return call_groq(user_prompt, system, max_tokens=300, use_cache=False)


def generate_session_commentary(user_prompt: str, mode: str = "institutional") -> str:
    """Generate session intelligence commentary."""
    system = get_system_prompt(mode)
    return call_groq(user_prompt, system, max_tokens=200, use_cache=True)


def generate_summary(user_prompt: str, mode: str = "institutional") -> str:
    """Generate daily/weekly summary."""
    system = get_system_prompt(mode)
    return call_groq(user_prompt, system, max_tokens=400, use_cache=False)


def chat_response(
    messages: list[dict],
    mode: str = "institutional",
    max_tokens: int = 512,
) -> str:
    """Generate a conversational response using message history."""
    system = get_chat_system_prompt(mode)
    groq = _get_groq()
    try:
        resp = groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=max_tokens,
            temperature=0.5,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error("Groq chat error: %s", e)
        return "AI temporarily unavailable. Please try again."


def generate_alert_commentary(price: float, direction: str, target: float) -> str:
    """Short alert trigger message."""
    arrow = "▲" if direction == "above" else "▼"
    prompt = (
        f"XAUUSD alert triggered. Price is at {price}. "
        f"Alert: price has gone {direction} {target}. "
        "Write one tight institutional sentence explaining what this price level means "
        "and the immediate trade implication. No disclaimers."
    )
    return call_groq(prompt, get_system_prompt("institutional"), max_tokens=80, use_cache=False)
