# XAUUSD Gold AI — Institutional Research & Execution Framework

A professional-grade Telegram bot for quantitative XAUUSD (Gold) research, signal generation, backtesting, and edge monitoring. Built for traders who require institutional-quality analytics without institutional-level infrastructure costs.

---

## Overview

This system combines real-time market data, multi-strategy signal generation, and a self-evaluating analytics platform into a single Telegram-based terminal. All metrics are Python-computed from live market data. AI (Groq) is used exclusively to explain outputs, not to generate them.

**Core design principles:**
- No lookahead bias in any backtest or signal
- Python computes all metrics — AI explains findings only
- No mocked data anywhere in the system
- Full SQLite persistence for all research history
- Modular architecture — every engine is independently testable

---

## Features

### 📈 Trading

| Feature | Command | Description |
|---|---|---|
| Multi-TF Analysis | `/analyze` | 1H/4H/Daily AI signal with regime context |
| Live Chart | `/chart` | 48-hour OHLCV candlestick with volume |
| Live Price | `/gold` | Spot price + TF bias snapshot |
| Fibonacci | `/fibonacci` | Swing detection, retracement levels, confluence score |
| Smart Money | `/smc` | BOS, CHoCH, order blocks, FVGs, liquidity zones |
| Sessions | `/sessions` | Live session intelligence (London/NY/Asia) |
| Confluence | `/confluence` | Multi-strategy signal alignment score |
| Voting Engine | `/votes` | 5-strategy weighted consensus signal |

### 🧠 Analytics

| Feature | Command | Description |
|---|---|---|
| Backtesting | `/backtest fib 1H 30d` | Historical strategy simulation, no lookahead |
| Performance | `/performance` | Win rate, PF, expectancy, Sharpe, vol-adj score |
| Leaderboard | `/leaderboard` | 5-dimension strategy ranking (0–100 score) |
| Diagnostics | `/diagnostics` | Overfitting, regime failure, confidence drift detection |
| Optimization | `/optimize fib 1H 30d` | Parameter grid search with robustness scoring |
| Heatmap | `/heatmap` | Multi-TF signal alignment heatmap |
| Session Analytics | `/session` | Win rate by London/NY/Asia/Overlap session |

### 📚 Research

| Feature | Command | Description |
|---|---|---|
| Decay Monitor | `/decay` | 7d/30d/90d rolling edge deterioration detection |
| Edge Health | `/edge` | Composite edge health score (0–100) per strategy |
| Regime Health | `/regimehealth` | Strategy performance across trending/ranging/volatile regimes |
| Stability | `/stability` | Consistency, confidence calibration, stability rankings |
| Strategy Compare | `/compare fib smc` | Side-by-side metric comparison with visual chart |
| Monitor | `/monitor` | System status and manual snapshot trigger |

### ⚙️ System

| Feature | Command | Description |
|---|---|---|
| Price Alerts | `/alert above 3300` | Threshold-based Telegram price alerts |
| Daily Summary | `/summary 08:00` | Scheduled market recap at your chosen UTC time |
| AI Mode | Via menu | Switch between Institutional / Scalper / Swing / Macro personas |
| Settings | Via menu | Configure all preferences |

---

## Architecture

```
xauusd-gold-ai/
│
├── main.py                    # Entry point, command registration, scheduler
│
├── market/
│   ├── data.py                # yfinance data fetching, OHLCV, live price
│   └── regime.py              # Market regime detection (trending/ranging/volatile)
│
├── strategies/
│   ├── fibonacci.py           # Swing detection, Fibonacci levels, confluence scoring
│   ├── smc.py                 # BOS, CHoCH, order blocks, FVGs, liquidity
│   ├── session.py             # Session analysis (London/NY/Asia ranges and bias)
│   └── momentum.py            # RSI, MACD, momentum indicators
│
├── signals/
│   ├── confluence.py          # Multi-strategy alignment scoring
│   ├── voting.py              # 5-strategy weighted voting engine
│   └── heatmap.py             # Multi-timeframe signal heatmap
│
├── analytics/
│   ├── performance.py         # Core stats engine: WR, PF, expectancy, Sharpe
│   ├── leaderboard.py         # 5-dimension strategy ranking system
│   ├── diagnostics.py         # Overfitting, decay, regime failure detection
│   ├── optimizer.py           # Parameter grid search and robustness scoring
│   ├── decay.py               # 7d/30d/90d rolling edge deterioration engine
│   ├── monitoring.py          # Daily snapshot and decay check scheduler jobs
│   ├── alerts.py              # Telegram alert dispatcher for edge events
│   └── session_analytics.py   # Session-based performance breakdown
│
├── backtesting/
│   ├── engine.py              # Backtest runner, trade simulation
│   ├── metrics.py             # Metrics computation (no lookahead)
│   ├── replay.py              # Historical bar replay engine
│   └── reports.py             # Chart generation for backtest results
│
├── charts/
│   └── chart_generator.py     # All chart generation (dark institutional theme)
│
├── ai/
│   ├── ai_router.py           # Groq API client with retry and caching
│   ├── prompts.py             # Strategy-specific prompt builders
│   └── cache.py               # Response caching layer
│
├── bot/
│   ├── handlers/
│   │   ├── commands.py              # Core command handlers
│   │   ├── callbacks.py             # Inline keyboard router (all UI flows)
│   │   ├── institutional_commands.py # Backtest, votes, heatmap handlers
│   │   ├── analytics_commands.py    # Performance, leaderboard, diagnostics
│   │   ├── decay_commands.py        # Decay, edge, regime, stability handlers
│   │   └── session_commands.py      # Session analytics handler
│   └── keyboards/
│       └── menus.py                 # All inline keyboard builders (4-section UI)
│
└── storage/
    └── database.py            # SQLite schema, all DB operations, thread-safe
```

### Database Schema

| Table | Purpose |
|---|---|
| `conversations` | Chat history per user |
| `price_alerts` | Threshold price alerts |
| `summary_settings` | Daily summary schedules |
| `ai_mode_settings` | Per-user AI persona |
| `backtest_runs` | Backtest metadata and results |
| `backtest_trades` | Individual simulated trades |
| `signal_history` | Historical signal log |
| `optimization_runs` | Parameter optimization results |
| `performance_snapshots` | Daily snapshots for decay tracking |
| `regime_statistics` | Per-regime performance breakdown |

---

## Deployment

### Environment Variables

| Variable | Required | Where to get |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | [t.me/BotFather](https://t.me/BotFather) → `/newbot` |
| `GROQ_API_KEY` | Yes | [console.groq.com](https://console.groq.com) → API Keys |

**Never commit these to version control.**

---

### Option 1 — Replit (Recommended)

1. Fork or import this repository into [replit.com](https://replit.com)
2. Open **Secrets** (padlock icon in sidebar)
3. Add `TELEGRAM_BOT_TOKEN` and `GROQ_API_KEY` as secrets
4. Click **Run** or start the `Start application` workflow
5. The bot will start polling automatically
6. For persistent 24/7 uptime, use **Replit Deployments** (Autoscale or Reserved VM)

> **Note:** Free Replit instances sleep after inactivity. Use Deployments for production.

---

### Option 2 — Local (Windows)

```powershell
# 1. Install Python 3.11+ from python.org

# 2. Clone
git clone https://github.com/youruser/xauusd-gold-ai
cd xauusd-gold-ai

# 3. Create venv
python -m venv venv
venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Set environment variables
set TELEGRAM_BOT_TOKEN=your_token_here
set GROQ_API_KEY=your_key_here

# 6. Run
python main.py
```

---

### Option 3 — Local (Linux / macOS)

```bash
git clone https://github.com/youruser/xauusd-gold-ai
cd xauusd-gold-ai

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="your_token"
export GROQ_API_KEY="your_key"

python main.py
```

---

### Option 4 — Ubuntu VPS (Production)

```bash
# 1. System setup
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv git -y

# 2. Clone
git clone https://github.com/youruser/xauusd-gold-ai /opt/goldbot
cd /opt/goldbot

# 3. Venv + install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Secrets file
cat > /opt/goldbot/.env << EOF
TELEGRAM_BOT_TOKEN=your_token_here
GROQ_API_KEY=your_key_here
EOF
chmod 600 /opt/goldbot/.env

# 5. Systemd service
sudo tee /etc/systemd/system/goldbot.service << EOF
[Unit]
Description=XAUUSD Gold AI Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/goldbot
EnvironmentFile=/opt/goldbot/.env
ExecStart=/opt/goldbot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable and start
sudo systemctl daemon-reload
sudo systemctl enable goldbot
sudo systemctl start goldbot

# Check logs
sudo journalctl -u goldbot -f
```

---

### Option 5 — Docker

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

Create `docker-compose.yml`:

```yaml
version: "3.9"
services:
  goldbot:
    build: .
    restart: unless-stopped
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - GROQ_API_KEY=${GROQ_API_KEY}
    volumes:
      - ./data:/app/data
```

```bash
# Build and run
docker compose up -d

# Logs
docker compose logs -f

# Restart
docker compose restart
```

---

## Bot Operation Guide

### 4-Section Navigation

```
┌─────────────────────────────────┐
│  XAUUSD Gold AI Terminal        │
└─────────────────────────────────┘

[ 📈 Trading ]    [ 🧠 Analytics ]
[ 📚 Research ]   [ ⚙️ System    ]
```

Every screen includes **🔄 Refresh**, **🔙 Back**, and **🏠 Home** navigation.
The entire bot is operable via buttons — slash commands are optional.

### 📈 Trading submenu

| Button | Action |
|---|---|
| 📊 Analyze | Multi-TF AI signal |
| 📈 Chart | 48h candlestick |
| 📐 Fibonacci | TF → analysis |
| 🏦 Smart Money | TF → SMC analysis |
| 🕐 Sessions | Live session intelligence |
| ◆ Confluence | Signal alignment score |
| 🗳 Voting | 5-strategy consensus |
| 💰 Live Price | Spot price snapshot |

### 🧠 Analytics submenu

| Button | Action |
|---|---|
| 📊 Backtest | Strategy → TF → Range → Results |
| 📈 Performance | Full dashboard |
| 🩺 Diagnostics | Health flags |
| 🌡 Heatmap | Multi-TF alignment |
| 📉 Decay | Edge deterioration |
| 🏆 Leaderboard | Ranked strategies |
| ⚙️ Optimize | Parameter grid search |
| 🕐 Sessions | Session-based analytics |

### 📚 Research submenu

| Button | Action |
|---|---|
| 🕸 Regime Health | Regime performance radar |
| 🔬 Edge Health | Composite edge scores |
| 📊 Stability | Consistency rankings |
| ⚖️ Compare | Strategy A vs B |
| 📋 Weekly Report | Combined research digest |
| 📡 Monitor | System status |

### ⚙️ System submenu

| Button | Action |
|---|---|
| 🔔 Alerts | Set/view price alerts |
| 📰 Summary | Schedule daily recap |
| 🤖 AI Mode | Switch persona |
| ⚙️ Settings | All preferences |
| ❓ Help | Full command list |

---

## Backtesting Guide

### How backtests work

1. Data is fetched for the requested period and timeframe using yfinance
2. The bar replay engine processes bars one at a time, left to right
3. Signals are generated using only data available at that point in time
4. Entries execute on the next bar's open after signal generation
5. Exits use stop-loss and take-profit levels defined at entry
6. All trades are stored in `backtest_trades` with session and regime tags

### No Lookahead Bias

The replay engine enforces strict time ordering. No future bar data is ever available to the signal generator during a simulation. This is enforced at the architectural level, not just by convention.

### Interpreting Results

| Metric | What It Tells You |
|---|---|
| Win Rate | % of trades closed in profit |
| Profit Factor | Total wins / total losses — must be > 1.0 |
| Expectancy | Average expected points per trade |
| Max Drawdown | Worst peak-to-trough during the period |
| Avg RR | Average actual risk-reward achieved |
| Trade Count | Too few (<30) makes results unreliable |

---

## Analytics Guide

### Key Metrics

| Metric | Good Range | Concern |
|---|---|---|
| Win Rate | > 50% | < 40% = weak edge |
| Profit Factor | > 1.5 | < 1.0 = loss-making |
| Expectancy | > 0 | < 0 = negative edge |
| Sharpe | > 1.0 | < 0.5 = poor risk-adj |
| Max Drawdown | < 25% | > 40% = too risky |
| Edge Health | > 65 | < 40 = critical |
| Stability | > 60% | < 40% = fragile |

### Edge Health Grades

| Score | Grade | Action |
|---|---|---|
| 90–100 | Institutional Grade | Full confidence |
| 75–89 | Strong Edge | Trade with standard sizing |
| 60–74 | Degrading | Reduce position size |
| 40–59 | Weak Edge | Avoid trading, investigate |
| 0–39 | Critical Failure | Stop trading, re-evaluate |

### Decay Monitoring

The decay engine compares rolling 7-day, 30-day, and 90-day performance windows. When recent performance diverges significantly from historical norms, alerts are raised automatically through the daily monitoring scheduler.

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| Bot not responding | Wrong token | Verify `TELEGRAM_BOT_TOKEN` |
| 409 Conflict on startup | Old instance alive | Wait 30–60 seconds |
| Groq API errors | Rate limit or bad key | Check console.groq.com |
| yfinance empty data | Market closed | Retry during market hours |
| Chart not sending | Matplotlib config | Ensure `Agg` backend in chart files |
| SQLite locked | Concurrent writes | Lock is handled automatically |
| Empty backtest | Too few candles | Use longer lookback period |
| Replit sleeps | Free tier | Use Replit Deployments |

---

## Security

- Store all secrets in environment variables — never in source code
- Add `.env` and `*.db` to `.gitignore`
- Keep your bot token private — it grants full bot control to anyone who has it
- For VPS deployments, use `chmod 600` on your `.env` file
- Consider keeping the repository private if deploying with sensitive configuration

**Recommended `.gitignore` additions:**
```
.env
*.db
*.sqlite3
__pycache__/
venv/
.pythonlibs/
attached_assets/
```

---

## Disclaimer

This software is provided **for educational and research purposes only**.

- This is NOT financial advice
- Past backtest performance does NOT guarantee future results
- Do NOT use outputs from this system to make real trading decisions without independent verification
- The authors accept no liability for any trading losses

---

## License

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is provided to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

---

## Roadmap

- [ ] Multi-asset support (Silver, Oil, indices)
- [ ] Live trade journaling with outcome tracking
- [ ] Walk-forward optimization validation
- [ ] Portfolio-level drawdown management
- [ ] Webhook mode for production deployments
- [ ] Strategy correlation matrix
- [ ] Web dashboard (FastAPI + React)
