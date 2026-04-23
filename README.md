# WealthSimply Monitor

A Python-based trading intelligence bot that monitors stock positions via SnapTrade, calculates technical indicators, and sends buy signals over Telegram. Designed for self-hosted use on a local server.

**No trade execution** — notify and log only.

## Features

- **SnapTrade integration** — syncs holdings across all linked Wealthsimple accounts (TFSA, RRSP, personal)
- **50-day SMA signals** — alerts when a stock drops below a configurable percentage of its 50-day simple moving average
- **Target price triggers** — set a target price on any watchlist symbol and get notified when it's hit
- **Batch price fetching** — single yfinance API call for all symbols per cycle
- **Telegram notifications** — real-time buy signals delivered to your phone
- **Web dashboard** — dark-themed single-page dashboard for holdings, watchlist management, and signal history
- **Market hours aware** — only polls during NYSE/TSX trading hours (Mon–Fri 9:30 AM – 4:00 PM ET)
- **Multi-account aggregation** — weighted average cost calculated across accounts holding the same symbol

## Architecture

```
bot.py          → Main polling loop (market hours, sync, evaluate)
api_client.py   → SnapTrade SDK wrapper with retry/backoff
market_data.py  → yfinance integration, symbol mapping, batch fetching
engine.py       → SMA calculation, signal evaluation
database.py     → SQLAlchemy models (Stock, PriceHistory, PollingLog, Signal)
notifier.py     → Telegram Bot API
web.py          → Flask dashboard (port 5050)
manage.py       → CLI for manual operations
config.py       → Environment config
```

## Setup

### Prerequisites

- Python 3.10+
- A [SnapTrade](https://snaptrade.com) API key with a connected Wealthsimple account
- A Telegram bot token (via [@BotFather](https://t.me/BotFather))

### Install

```bash
git clone https://github.com/navsivapatham/wealthsimply-monitor.git
cd wealthsimply-monitor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

Create a `.env` file:

```env
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key
SNAPTRADE_USER_ID=your_user_id
SNAPTRADE_USER_SECRET=your_user_secret

TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Run

```bash
# Start the monitoring bot
python bot.py

# Start the web dashboard
python web.py

# CLI commands
python manage.py sync              # Sync holdings from SnapTrade
python manage.py status            # Show current positions
python manage.py watch AAPL --target 150
python manage.py backfill AAPL     # Backfill price history
```

## Dashboard

The web dashboard runs on port 5050 and includes:

- **Holdings** — current positions with average cost and live prices
- **Watchlist** — add/remove symbols, set target prices and SMA thresholds, refresh prices
- **Signals** — history of all generated buy signals

No authentication — designed for local network access only.

## Deployment

The bot and dashboard can run as systemd services. Example unit files:

**Monitor** (runs during market hours via systemd timer):
```ini
[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/wealthsimply-monitor
ExecStart=/path/to/venv/bin/python bot.py
```

**Web dashboard** (always on):
```ini
[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/wealthsimply-monitor
ExecStart=/path/to/venv/bin/python web.py
Restart=always
```

## Symbol Mapping

Wealthsimple symbols don't always match yfinance tickers. The `SYMBOL_MAP` in `market_data.py` handles translation:

- TSX stocks: `ATZ` → `ATZ.TO`
- Crypto: `ETH` → `ETH-USD`
- Special cases: `BTCC.B` → `BTCC-B.TO`

Add custom mappings as needed.

## License

MIT
