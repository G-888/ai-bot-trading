import os
import io
import json
import logging
from datetime import datetime, timezone
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf
import yfinance as yf
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from groq import Groq

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

groq_client = Groq(api_key=GROQ_API_KEY)

conversation_history: dict[int, list[dict]] = {}

# alerts[chat_id] = [{"id": int, "direction": "above"|"below", "price": float}]
alerts: dict[int, list[dict]] = {}
_alert_id_counter = 0

# summary_schedules[chat_id] = "HH:MM"  (UTC)
summary_schedules: dict[int, str] = {}

# tracks the last datetime a summary was sent per user to prevent duplicates
_summary_last_sent: dict[int, str] = {}

PREFS_FILE = "user_prefs.json"


# ── Persistence ────────────────────────────────────────────────────────────────

def load_prefs() -> None:
    global summary_schedules
    if not os.path.exists(PREFS_FILE):
        return
    try:
        with open(PREFS_FILE) as f:
            data = json.load(f)
        summary_schedules = {int(k): v for k, v in data.get("summary_schedules", {}).items()}
        logger.info("Loaded prefs: %d summary schedule(s)", len(summary_schedules))
    except Exception as e:
        logger.error("Failed to load prefs: %s", e)


def save_prefs() -> None:
    try:
        data = {"summary_schedules": {str(k): v for k, v in summary_schedules.items()}}
        with open(PREFS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error("Failed to save prefs: %s", e)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _next_alert_id() -> int:
    global _alert_id_counter
    _alert_id_counter += 1
    return _alert_id_counter


SYSTEM_PROMPT = (
    "You are a senior institutional gold analyst at a top-tier macro fund. "
    "Deliver multi-timeframe trade signals with precision and authority. "
    "No disclaimers, no hedging language, no 'as an AI'. "
    "Always format your response EXACTLY like this — no deviations:\n\n"
    "XAUUSD\n"
    "Price: {price}\n\n"
    "1H Bias: Bullish / Bearish / Neutral\n"
    "4H Trend: Bullish / Bearish / Neutral\n"
    "Daily Momentum: Bullish / Bearish / Neutral\n\n"
    "Alignment: [Full Bull Alignment / Bearish Bias / Conflicting Structure / etc.]\n\n"
    "Signal: BUY or SELL\n"
    "Confidence: XX%\n\n"
    "Support: XXXX  |  Resistance: XXXX\n\n"
    "Reason:\n"
    "Exactly 3 sentences. "
    "Sentence 1: state the dominant structure and which timeframes are aligned or conflicting. "
    "Sentence 2: describe the key momentum condition — accelerating, decelerating, diverging — and "
    "the most critical level (demand zone, supply rejection, liquidity sweep). "
    "Sentence 3: give the session bias and what confirms or invalidates the signal. "
    "Use terms: structure break, liquidity grab, EMA compression, momentum divergence, "
    "demand/supply zone, session open bias, confluence. Be institutional. No filler."
)


def _tf_bias(df, lookback: int, threshold: float = 0.3) -> tuple[str, float]:
    """Return (bias_label, pct_change) for a given dataframe and lookback period."""
    if len(df) < lookback + 1:
        return "Neutral", 0.0
    current = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-lookback])
    pct = (current - prev) / prev * 100
    if pct > threshold:
        return "Bullish", round(pct, 2)
    elif pct < -threshold:
        return "Bearish", round(pct, 2)
    return "Neutral", round(pct, 2)


def _tf_structure(df, lookback: int) -> tuple[float, float]:
    """Return (support, resistance) from the last `lookback` candles."""
    recent = df.tail(lookback)
    return round(float(recent["Low"].min()), 2), round(float(recent["High"].max()), 2)


def _momentum_label(df, fast: int = 5, slow: int = 20) -> str:
    """EMA crossover-based momentum: Accelerating / Decelerating / Flat."""
    if len(df) < slow + 1:
        return "Flat"
    closes = df["Close"]
    ema_fast = float(closes.ewm(span=fast, adjust=False).mean().iloc[-1])
    ema_slow = float(closes.ewm(span=slow, adjust=False).mean().iloc[-1])
    prev_ema_fast = float(closes.ewm(span=fast, adjust=False).mean().iloc[-2])
    prev_ema_slow = float(closes.ewm(span=slow, adjust=False).mean().iloc[-2])
    gap_now = ema_fast - ema_slow
    gap_prev = prev_ema_fast - prev_ema_slow
    if abs(gap_now) < abs(ema_slow) * 0.001:
        return "Flat"
    if gap_now > gap_prev:
        return "Accelerating"
    return "Decelerating"


def fetch_gold_data() -> dict | None:
    try:
        ticker = yf.Ticker("GC=F")

        # ── 1H  (last 5 days — short-term bias)
        h1 = ticker.history(period="5d", interval="1h")
        if h1.empty:
            return None

        current_price = round(float(h1["Close"].iloc[-1]), 2)

        h1_bias, h1_pct = _tf_bias(h1, lookback=6, threshold=0.15)
        h1_support, h1_resistance = _tf_structure(h1, lookback=24)

        # Intra-1H volatility
        recent_1h = h1.tail(24)
        avg_range = float((recent_1h["High"] - recent_1h["Low"]).mean())
        vol_ratio = avg_range / current_price * 100
        volatility = "High" if vol_ratio > 1.0 else ("Medium" if vol_ratio > 0.5 else "Low")

        # ── 4H  (last 30 days — intermediate trend)
        h4 = ticker.history(period="30d", interval="4h")
        if h4.empty:
            h4_trend, h4_pct = "Neutral", 0.0
            h4_support, h4_resistance = h1_support, h1_resistance
            h4_momentum = "Flat"
        else:
            h4_trend, h4_pct = _tf_bias(h4, lookback=10, threshold=0.3)
            h4_support, h4_resistance = _tf_structure(h4, lookback=30)
            h4_momentum = _momentum_label(h4)

        # ── Daily  (last 90 days — macro momentum)
        d1 = ticker.history(period="90d", interval="1d")
        if d1.empty:
            d1_momentum, d1_pct = "Neutral", 0.0
            d1_support, d1_resistance = h1_support, h1_resistance
            d1_ema_state = "Flat"
        else:
            d1_momentum, d1_pct = _tf_bias(d1, lookback=14, threshold=0.5)
            d1_support, d1_resistance = _tf_structure(d1, lookback=20)
            d1_ema_state = _momentum_label(d1, fast=9, slow=21)

        # Alignment check
        biases = [h1_bias, h4_trend, d1_momentum]
        bull_count = biases.count("Bullish")
        bear_count = biases.count("Bearish")
        if bull_count == 3:
            alignment = "Full Bull Alignment"
        elif bear_count == 3:
            alignment = "Full Bear Alignment"
        elif bull_count == 2:
            alignment = "Bullish Bias (partial)"
        elif bear_count == 2:
            alignment = "Bearish Bias (partial)"
        else:
            alignment = "Conflicting Structure"

        return {
            "price": current_price,
            "volatility": volatility,
            "alignment": alignment,
            # 1H
            "h1_bias": h1_bias,
            "h1_pct": h1_pct,
            "h1_support": h1_support,
            "h1_resistance": h1_resistance,
            # 4H
            "h4_trend": h4_trend,
            "h4_pct": h4_pct,
            "h4_support": h4_support,
            "h4_resistance": h4_resistance,
            "h4_momentum": h4_momentum,
            # Daily
            "d1_momentum": d1_momentum,
            "d1_pct": d1_pct,
            "d1_support": d1_support,
            "d1_resistance": d1_resistance,
            "d1_ema_state": d1_ema_state,
            # Legacy keys kept for chart/summary/alerts compatibility
            "support": h1_support,
            "resistance": h1_resistance,
            "trend": h4_trend,
            "pct_change": h4_pct,
            "closes": h1["Close"].tail(24).tolist(),
            "highs": h1["High"].tail(24).tolist(),
            "lows": h1["Low"].tail(24).tolist(),
            "volumes": h1["Volume"].tail(24).tolist(),
            "df": h1,
        }
    except Exception as e:
        logger.error("Failed to fetch gold data: %s", e)
        return None


def get_alert_commentary(price: float, direction: str, target: float) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior institutional gold desk analyst. "
                        "When a price level is breached, deliver one sharp sentence of market context. "
                        "Reference structure, momentum, or session significance. "
                        "No disclaimers. No filler. Sound like a Bloomberg terminal alert."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"XAUUSD just printed {price}, breaching the {target} level to the {direction}. "
                        "One sentence of professional market context."
                    ),
                },
            ],
            max_tokens=60,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Groq commentary error: %s", e)
        return "Key level breached — monitor for follow-through or reversal."


def get_daily_outlook(data: dict) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior institutional gold analyst writing the morning brief "
                        "for a macro trading desk. Deliver a sharp, high-conviction session outlook "
                        "in 2-3 sentences maximum. Cover: dominant structure bias, key level to watch, "
                        "and likely session behaviour (range-bound, breakout, reversal risk). "
                        "Use precise trading language: bid/offer side, liquidity, momentum, "
                        "structure hold/break, London/NY/Asia session bias. "
                        "No disclaimers. No 'as an AI'. No generic filler. Write like a desk note."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"XAUUSD: {data['price']} | "
                        f"24h trend: {data['trend']} ({data['pct_change']:+.2f}%) | "
                        f"Support: {data['support']} | Resistance: {data['resistance']} | "
                        f"Volatility: {data['volatility']} | "
                        f"Last 6 closes: {data['closes'][-6:]}\n\n"
                        "Write the session outlook."
                    ),
                },
            ],
            max_tokens=120,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Groq outlook error: %s", e)
        return "Structure intact — watch key levels for directional break."


def build_summary_message(data: dict, scheduled_time: str) -> str:
    trend_arrow = "▲" if data["trend"] == "Bullish" else ("▼" if data["trend"] == "Bearish" else "→")
    outlook = get_daily_outlook(data)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return (
        f"📊 Daily XAUUSD Summary\n"
        f"{now_str}\n\n"
        f"Price: {data['price']}\n"
        f"Trend: {trend_arrow} {data['trend']} ({data['pct_change']:+.2f}%)\n"
        f"Support: {data['support']}\n"
        f"Resistance: {data['resistance']}\n"
        f"Volatility: {data['volatility']}\n\n"
        f"AI Outlook:\n{outlook}"
    )


# ── Background jobs ────────────────────────────────────────────────────────────

async def check_alerts(context) -> None:
    if not alerts:
        return

    data = fetch_gold_data()
    if not data:
        logger.warning("Alert check: could not fetch gold price")
        return

    current_price = data["price"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    triggered: dict[int, list[dict]] = {}

    for chat_id, user_alerts in list(alerts.items()):
        fired = []
        remaining = []
        for a in user_alerts:
            hit = (
                (a["direction"] == "above" and current_price >= a["price"])
                or (a["direction"] == "below" and current_price <= a["price"])
            )
            if hit:
                fired.append(a)
            else:
                remaining.append(a)

        if fired:
            triggered[chat_id] = fired
            alerts[chat_id] = remaining
            if not alerts[chat_id]:
                del alerts[chat_id]

    for chat_id, fired_alerts in triggered.items():
        for a in fired_alerts:
            commentary = get_alert_commentary(current_price, a["direction"], a["price"])
            arrow = "▲" if a["direction"] == "above" else "▼"
            msg = (
                f"🔔 XAUUSD Alert Triggered!\n\n"
                f"{arrow} Target: {a['price']} ({a['direction']})\n"
                f"Current Price: {current_price}\n"
                f"Time: {now}\n\n"
                f"AI Commentary:\n{commentary}"
            )
            try:
                await context.bot.send_message(chat_id=chat_id, text=msg)
            except Exception as e:
                logger.error("Failed to send alert to %s: %s", chat_id, e)


async def check_summaries(context) -> None:
    if not summary_schedules:
        return

    now_utc = datetime.now(timezone.utc)
    current_hhmm = now_utc.strftime("%H:%M")
    current_date = now_utc.strftime("%Y-%m-%d")

    due = [
        chat_id
        for chat_id, sched_time in summary_schedules.items()
        if sched_time == current_hhmm
        and _summary_last_sent.get(chat_id) != f"{current_date} {current_hhmm}"
    ]

    if not due:
        return

    data = fetch_gold_data()
    if not data:
        logger.warning("Summary check: could not fetch gold data")
        return

    for chat_id in due:
        sched_time = summary_schedules.get(chat_id, current_hhmm)
        try:
            msg = build_summary_message(data, sched_time)
            await context.bot.send_message(chat_id=chat_id, text=msg)
            _summary_last_sent[chat_id] = f"{current_date} {current_hhmm}"
            logger.info("Sent daily summary to %s", chat_id)
        except Exception as e:
            logger.error("Failed to send summary to %s: %s", chat_id, e)


# ── Chart ──────────────────────────────────────────────────────────────────────

def generate_chart(df, price: float, support: float, resistance: float) -> io.BytesIO:
    df = df.tail(48).copy()
    df.index = df.index.tz_localize(None) if df.index.tzinfo is not None else df.index

    dark_style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        facecolor="#0d1117",
        edgecolor="#30363d",
        figcolor="#0d1117",
        gridcolor="#21262d",
        gridstyle="--",
        gridaxis="both",
        y_on_right=True,
        rc={
            "axes.labelcolor": "#8b949e",
            "xtick.color": "#8b949e",
            "ytick.color": "#8b949e",
            "font.size": 9,
        },
    )

    price_line = [price] * len(df)
    support_line = [support] * len(df)
    resistance_line = [resistance] * len(df)

    add_plots = [
        mpf.make_addplot(price_line, color="#f0c040", width=1.2, linestyle="--"),
        mpf.make_addplot(support_line, color="#3fb950", width=1.5),
        mpf.make_addplot(resistance_line, color="#f85149", width=1.5),
    ]

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=dark_style,
        volume=True,
        addplot=add_plots,
        figsize=(10, 6),
        title="",
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=9999,
        volume_panel=1,
        panel_ratios=(3, 1),
    )

    ax_main = axes[0]
    ax_main.set_title(
        "  XAUUSD  •  48h Candlestick",
        color="#f0f6fc",
        fontsize=13,
        fontweight="bold",
        loc="left",
        pad=10,
    )

    legend_patches = [
        mpatches.Patch(color="#f0c040", label=f"Price: {price}"),
        mpatches.Patch(color="#3fb950", label=f"Support: {support}"),
        mpatches.Patch(color="#f85149", label=f"Resistance: {resistance}"),
    ]
    ax_main.legend(
        handles=legend_patches,
        loc="upper left",
        framealpha=0.3,
        facecolor="#161b22",
        edgecolor="#30363d",
        labelcolor="#f0f6fc",
        fontsize=8,
    )

    fig.patch.set_facecolor("#0d1117")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="#0d1117")
    buf.seek(0)
    plt.close(fig)
    return buf


# ── Command handlers ───────────────────────────────────────────────────────────

async def send_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Generating XAUUSD chart...")

    data = fetch_gold_data()
    if not data:
        await update.message.reply_text("Could not fetch chart data. Please try again later.")
        return

    try:
        buf = generate_chart(data["df"], data["price"], data["support"], data["resistance"])
        caption = (
            f"XAUUSD  •  48h Chart\n"
            f"Price: {data['price']}\n"
            f"Support: {data['support']}  |  Resistance: {data['resistance']}"
        )
        await update.message.reply_photo(photo=buf, caption=caption)
    except Exception as e:
        logger.error("Chart generation error: %s", e)
        await update.message.reply_text("Failed to generate chart. Please try again.")


async def analyze_gold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Fetching live XAUUSD data...")

    data = fetch_gold_data()
    if not data:
        await update.message.reply_text("Could not fetch gold price data. Please try again later.")
        return

    prompt = (
        f"Price: {data['price']}\n\n"
        f"── 1H (Short-Term Bias) ──\n"
        f"Bias: {data['h1_bias']} ({data['h1_pct']:+.2f}% over 6 bars)\n"
        f"Support: {data['h1_support']}  Resistance: {data['h1_resistance']}\n"
        f"Recent closes: {[round(c,2) for c in data['closes'][-8:]]}\n\n"
        f"── 4H (Intermediate Trend) ──\n"
        f"Trend: {data['h4_trend']} ({data['h4_pct']:+.2f}% over 10 bars)\n"
        f"Momentum: {data['h4_momentum']}\n"
        f"Support: {data['h4_support']}  Resistance: {data['h4_resistance']}\n\n"
        f"── Daily (Macro Momentum) ──\n"
        f"Momentum: {data['d1_momentum']} ({data['d1_pct']:+.2f}% over 14 days)\n"
        f"EMA state: {data['d1_ema_state']}\n"
        f"Support: {data['d1_support']}  Resistance: {data['d1_resistance']}\n\n"
        f"── Structure ──\n"
        f"Alignment: {data['alignment']}\n"
        f"Volatility: {data['volatility']}\n\n"
        "Deliver the multi-timeframe signal in the exact format specified."
    )

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
        )
        reply = response.choices[0].message.content
    except Exception as e:
        logger.error("Groq API error: %s", e)
        reply = "AI analysis failed. Please try again."

    await update.message.reply_text(reply)


async def gold_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = fetch_gold_data()
    if not data:
        await update.message.reply_text("Could not fetch gold price. Please try again later.")
        return
    await update.message.reply_text(
        f"XAUUSD\n"
        f"Price: {data['price']}\n\n"
        f"Support: {data['support']}\n"
        f"Resistance: {data['resistance']}\n\n"
        "Use /analyze for a full AI-powered signal.\n"
        "Use /chart for a candlestick chart."
    )


async def set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text(
            "Usage:\n"
            "/alert above 3250\n"
            "/alert below 3200\n\n"
            "Sets an alert that fires when XAUUSD crosses your target price."
        )
        return

    direction = args[0].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text("Direction must be 'above' or 'below'.")
        return

    try:
        target_price = float(args[1])
    except ValueError:
        await update.message.reply_text("Price must be a number, e.g. /alert above 3250")
        return

    alert_entry = {
        "id": _next_alert_id(),
        "direction": direction,
        "price": target_price,
    }
    alerts.setdefault(chat_id, []).append(alert_entry)

    arrow = "▲" if direction == "above" else "▼"
    await update.message.reply_text(
        f"Alert set!\n\n"
        f"{arrow} Notify me when XAUUSD goes {direction} {target_price}\n\n"
        f"Checks every 60 seconds. Use /alerts to see all active alerts."
    )


async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_alerts = alerts.get(chat_id, [])

    if not user_alerts:
        await update.message.reply_text(
            "You have no active alerts.\n\nSet one with:\n/alert above 3250\n/alert below 3200"
        )
        return

    lines = ["Active XAUUSD Alerts:\n"]
    for a in user_alerts:
        arrow = "▲" if a["direction"] == "above" else "▼"
        lines.append(f"{arrow} {a['direction'].capitalize()} {a['price']}  (ID #{a['id']})")

    lines.append("\nUse /clearalerts to remove all alerts.")
    await update.message.reply_text("\n".join(lines))


async def clear_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    count = len(alerts.pop(chat_id, []))
    if count:
        await update.message.reply_text(f"Cleared {count} alert{'s' if count != 1 else ''}.")
    else:
        await update.message.reply_text("You have no active alerts to clear.")


async def set_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) != 1:
        await update.message.reply_text(
            "Usage:\n"
            "/summary 08:00\n"
            "/summary 20:30\n\n"
            "Sets a daily XAUUSD market summary at your chosen time (UTC).\n"
            "Use /summaryoff to disable."
        )
        return

    time_str = args[0].strip()
    try:
        t = datetime.strptime(time_str, "%H:%M")
        formatted = t.strftime("%H:%M")
    except ValueError:
        await update.message.reply_text(
            "Invalid time format. Use HH:MM, e.g. /summary 08:00"
        )
        return

    summary_schedules[chat_id] = formatted
    save_prefs()

    await update.message.reply_text(
        f"Daily summary scheduled!\n\n"
        f"I'll send you a XAUUSD market recap every day at {formatted} UTC.\n\n"
        "Use /summaryoff to disable."
    )


async def summary_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in summary_schedules:
        del summary_schedules[chat_id]
        _summary_last_sent.pop(chat_id, None)
        save_prefs()
        await update.message.reply_text("Daily summary disabled.")
    else:
        await update.message.reply_text(
            "You don't have a daily summary scheduled.\n\n"
            "Set one with: /summary 08:00"
        )


async def send_summary_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send an immediate summary preview (triggered by /summary with no args or if user wants preview)."""
    await update.message.reply_text("Generating your XAUUSD summary...")

    data = fetch_gold_data()
    if not data:
        await update.message.reply_text("Could not fetch data. Please try again later.")
        return

    sched_time = summary_schedules.get(update.effective_chat.id, "now")
    msg = build_summary_message(data, sched_time)
    await update.message.reply_text(msg)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    conversation_history.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        f"Hello {user.first_name}! I'm your XAUUSD Gold Trading Assistant.\n\n"
        "Commands:\n"
        "/gold or /xauusd — live gold price\n"
        "/analyze — full AI trading signal\n"
        "/chart — 48h candlestick chart\n"
        "/alert above 3250 — set a price alert\n"
        "/alert below 3200 — set a price alert\n"
        "/alerts — list active alerts\n"
        "/clearalerts — remove all alerts\n"
        "/summary 08:00 — set daily recap time (UTC)\n"
        "/summaryoff — disable daily recap\n"
        "/clear — reset conversation\n\n"
        "Powered by live Yahoo Finance data + Groq AI."
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversation_history.pop(update.effective_chat.id, None)
    await update.message.reply_text("Conversation cleared.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.lower().strip()

    if any(kw in text for kw in ["analyze gold", "analyse gold", "gold signal", "xauusd signal", "gold analysis"]):
        await analyze_gold(update, context)
        return

    if any(kw in text for kw in ["gold chart", "xauusd chart", "show chart", "chart gold"]):
        await send_chart(update, context)
        return

    if any(kw in text for kw in ["gold price", "xauusd price", "gold rate", "price of gold"]):
        await gold_price(update, context)
        return

    if any(kw in text for kw in ["daily summary", "gold summary", "market summary", "xauusd summary"]):
        await send_summary_now(update, context)
        return

    chat_id = update.effective_chat.id
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({"role": "user", "content": update.message.text})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior institutional gold analyst at a macro trading desk. "
                        "Answer with authority and precision — no disclaimers, no 'as an AI', no hedging filler. "
                        "Use professional trading terminology: structure, momentum, liquidity, session bias, "
                        "confluence, volatility regime, demand/supply zones, risk-reward. "
                        "Be concise — maximum 3 short paragraphs. "
                        "If asked for an opinion or signal, give one directly with clear reasoning. "
                        "Write like a Bloomberg desk note, not a retail trading blog."
                    ),
                }
            ] + conversation_history[chat_id],
            max_tokens=512,
        )
        reply = response.choices[0].message.content
        conversation_history[chat_id].append({"role": "assistant", "content": reply})

        if len(conversation_history[chat_id]) > 20:
            conversation_history[chat_id] = conversation_history[chat_id][-20:]

    except Exception as e:
        logger.error("Groq API error: %s", e)
        reply = "Sorry, I encountered an error. Please try again."

    await update.message.reply_text(reply)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    load_prefs()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("gold", gold_price))
    app.add_handler(CommandHandler("xauusd", gold_price))
    app.add_handler(CommandHandler("analyze", analyze_gold))
    app.add_handler(CommandHandler("chart", send_chart))
    app.add_handler(CommandHandler("alert", set_alert))
    app.add_handler(CommandHandler("alerts", list_alerts))
    app.add_handler(CommandHandler("clearalerts", clear_alerts))
    app.add_handler(CommandHandler("summary", set_summary))
    app.add_handler(CommandHandler("summaryoff", summary_off))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(check_alerts, interval=60, first=15)
    app.job_queue.run_repeating(check_summaries, interval=60, first=20)

    logger.info("Gold Trading Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
