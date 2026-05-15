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
    "You are an expert gold (XAUUSD) trading analyst. "
    "When given gold price data, provide a clear BUY or SELL signal with confidence percentage, "
    "a short market explanation, and key support and resistance levels. "
    "Always format your response EXACTLY like this:\n\n"
    "XAUUSD\n"
    "Price: {price}\n\n"
    "Signal: BUY or SELL\n"
    "Confidence: XX%\n\n"
    "Support: XXXX\n"
    "Resistance: XXXX\n\n"
    "Reason:\n"
    "One to two sentence explanation of the signal.\n\n"
    "Be concise, professional, and data-driven."
)


def fetch_gold_data() -> dict | None:
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="5d", interval="1h")
        if hist.empty:
            return None

        current_price = round(float(hist["Close"].iloc[-1]), 2)
        recent = hist.tail(24)
        support = round(float(recent["Low"].min()), 2)
        resistance = round(float(recent["High"].max()), 2)

        # Trend: compare current close vs close 24 candles ago
        if len(hist) >= 25:
            prev_price = float(hist["Close"].iloc[-25])
            pct_change = (current_price - prev_price) / prev_price * 100
            if pct_change > 0.3:
                trend = "Bullish"
            elif pct_change < -0.3:
                trend = "Bearish"
            else:
                trend = "Neutral"
        else:
            trend = "Neutral"
            pct_change = 0.0

        # Volatility: (high - low) / close over last 24 candles
        avg_range = float((recent["High"] - recent["Low"]).mean())
        vol_ratio = avg_range / current_price * 100
        if vol_ratio > 1.0:
            volatility = "High"
        elif vol_ratio > 0.5:
            volatility = "Medium"
        else:
            volatility = "Low"

        return {
            "price": current_price,
            "support": support,
            "resistance": resistance,
            "trend": trend,
            "pct_change": round(pct_change, 2),
            "volatility": volatility,
            "closes": hist["Close"].tail(24).tolist(),
            "highs": hist["High"].tail(24).tolist(),
            "lows": hist["Low"].tail(24).tolist(),
            "volumes": hist["Volume"].tail(24).tolist(),
            "df": hist,
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
                        "You are a concise gold trading analyst. "
                        "Write a single short sentence (max 20 words) of market commentary "
                        "when a price alert is triggered. Be direct and professional."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"XAUUSD price just moved {direction} {target}. "
                        f"Current price is {price}. Give a brief one-sentence commentary."
                    ),
                },
            ],
            max_tokens=60,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Groq commentary error: %s", e)
        return "Monitor price action closely."


def get_daily_outlook(data: dict) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional gold market analyst. "
                        "Write a concise 1-2 sentence outlook for the next trading session "
                        "based on the data provided. Be specific, direct, and actionable."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"XAUUSD current price: {data['price']}\n"
                        f"Trend: {data['trend']} ({data['pct_change']:+.2f}% over 24h)\n"
                        f"Support: {data['support']}, Resistance: {data['resistance']}\n"
                        f"Volatility: {data['volatility']}\n"
                        f"Recent closes: {data['closes'][-6:]}\n\n"
                        "Give a 1-2 sentence outlook for the next trading session."
                    ),
                },
            ],
            max_tokens=80,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Groq outlook error: %s", e)
        return "Watch key levels closely for the next session."


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
        f"Current XAUUSD price: {data['price']}\n"
        f"Recent 24h closes: {data['closes']}\n"
        f"Recent 24h highs: {data['highs']}\n"
        f"Recent 24h lows: {data['lows']}\n"
        f"Recent 24h volumes: {data['volumes']}\n"
        f"Calculated support: {data['support']}\n"
        f"Calculated resistance: {data['resistance']}\n\n"
        "Analyze this data and provide a trading signal in the exact format specified."
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
                        "You are an expert gold (XAUUSD) trading assistant. "
                        "Help users understand gold markets, trading strategies, and analysis. "
                        "Be concise and professional."
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
