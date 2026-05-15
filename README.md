# XAUUSD Gold AI Trading Bot

A Telegram bot powered by Groq AI and live market data that delivers real-time gold (XAUUSD) trading signals, price alerts, and candlestick charts — directly in your Telegram chat.

## Features

- **Live Gold Price** — fetches real-time XAUUSD price from Yahoo Finance
- **AI Trading Signals** — BUY/SELL signals with confidence %, support/resistance levels, and reasoning powered by Groq (LLaMA 3.3 70B)
- **Candlestick Charts** — dark-themed 48h XAUUSD chart with support, resistance, and current price markers sent as images
- **Price Alerts** — set above/below price alerts; bot checks every 60 seconds and notifies you with AI commentary when triggered
- **Multi-user** — each user has independent conversation history and alerts

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and command list |
| `/gold` or `/xauusd` | Live XAUUSD price with support & resistance |
| `/analyze` | Full AI trading signal (BUY/SELL, confidence %, levels, reason) |
| `/chart` | 48h candlestick chart image |
| `/alert above 3250` | Alert when gold rises above 3250 |
| `/alert below 3200` | Alert when gold drops below 3200 |
| `/alerts` | List all your active alerts |
| `/clearalerts` | Remove all your active alerts |
| `/clear` | Reset conversation history |

## Example Output

```
XAUUSD
Price: 3215.50

Signal: BUY
Confidence: 82%

Support: 3200
Resistance: 3230

Reason:
Bullish momentum with strong buying pressure above support.
```

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/G-888/ai-bot-trading.git
cd ai-bot-trading
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
export TELEGRAM_BOT_TOKEN=your_telegram_bot_token
export GROQ_API_KEY=your_groq_api_key
```

- **TELEGRAM_BOT_TOKEN** — create a bot via [@BotFather](https://t.me/BotFather) on Telegram
- **GROQ_API_KEY** — get a free API key at [console.groq.com](https://console.groq.com)

### 4. Run the bot

```bash
python3 main.py
```

## Tech Stack

- **Python 3.11**
- **python-telegram-bot** — Telegram Bot API wrapper
- **Groq** — LLaMA 3.3 70B for AI analysis and alert commentary
- **yfinance** — live XAUUSD market data (Yahoo Finance, no API key required)
- **mplfinance + matplotlib** — candlestick chart generation
- **APScheduler** — background price alert checking every 60 seconds

## Data Source

Live gold prices are fetched from Yahoo Finance using the `GC=F` (Gold Futures) ticker via the `yfinance` library. No paid API key is required.

## Notes

- All data (alerts, conversation history) is stored in memory and resets when the bot restarts
- Price checks for alerts run every 60 seconds
- The bot uses the `llama-3.3-70b-versatile` model via Groq's free tier
