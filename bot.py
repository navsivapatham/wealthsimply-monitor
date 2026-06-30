import time
import logging
import signal as sig
from datetime import datetime
import pytz
from database import init_db, get_session, get_preference, Stock
from api_client import SnapTradeClient
from market_data import backfill_history, update_today, fetch_current_prices
from engine import run_evaluation
from notifier import TelegramNotifier
from config import (
    DEFAULT_POLL_INTERVAL, MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE, MARKET_TIMEZONE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

running = True


def handle_shutdown(signum, frame):
    global running
    log.info("Shutdown signal received")
    running = False


sig.signal(sig.SIGTERM, handle_shutdown)
sig.signal(sig.SIGINT, handle_shutdown)


def is_market_open() -> bool:
    et = pytz.timezone(MARKET_TIMEZONE)
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0)
    return market_open <= now <= market_close


def sync_holdings(client: SnapTradeClient):
    """Pull current positions from Wealthsimple and upsert into stocks table."""
    log.info("Syncing holdings from Wealthsimple...")
    positions = client.get_all_holdings()

    # Aggregate positions across accounts (same symbol in RRSP + TFSA = one row)
    aggregated: dict[str, dict] = {}
    for pos in positions:
        symbol = pos["symbol"]
        if not symbol:
            continue
        if symbol in aggregated:
            old = aggregated[symbol]
            old_value = old["shares"] * old["average_cost"]
            new_value = pos["units"] * pos["average_purchase_price"]
            total_shares = old["shares"] + pos["units"]
            old["shares"] = total_shares
            old["average_cost"] = (old_value + new_value) / total_shares if total_shares else 0
        else:
            aggregated[symbol] = {
                "shares": pos["units"],
                "average_cost": pos["average_purchase_price"],
                "company_name": pos["company_name"],
            }

    session = get_session()
    try:
        for symbol, data in aggregated.items():
            existing = session.query(Stock).filter_by(symbol=symbol).first()
            if existing and existing.source == "wealthsimple":
                existing.shares = data["shares"]
                existing.average_cost = data["average_cost"]
                existing.company_name = data["company_name"]
            elif not existing:
                session.add(Stock(
                    symbol=symbol,
                    company_name=data["company_name"],
                    average_cost=data["average_cost"],
                    shares=data["shares"],
                    source="wealthsimple",
                ))
                log.info(f"  + {symbol}: {data['shares']:.2f} shares @ ${data['average_cost']:.2f}")

        for stock in session.query(Stock).filter_by(source="wealthsimple").all():
            if stock.symbol not in aggregated:
                stock.shares = 0

        session.commit()
        log.info(f"Sync complete: {len(aggregated)} unique symbols across all accounts")
    finally:
        session.close()


def backfill_all():
    session = get_session()
    try:
        stocks = session.query(Stock).all()
    finally:
        session.close()
    for stock in stocks:
        backfill_history(stock.symbol)


def run():
    init_db()
    notifier = TelegramNotifier()
    client = SnapTradeClient()

    sync_holdings(client)
    backfill_all()

    session = get_session()
    stock_count = session.query(Stock).filter(Stock.shares > 0).count()
    watch_count = session.query(Stock).filter_by(is_watchlist=True).count()
    session.close()

    notifier.send_startup(stock_count, watch_count)
    log.info(f"Monitoring {stock_count} holdings, {watch_count} watchlist items")

    # If the timer fires before market open, wait rather than quitting immediately
    _et = pytz.timezone(MARKET_TIMEZONE)
    _now = datetime.now(_et)
    _open = _now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    if _now < _open:
        _wait = int((_open - _now).total_seconds()) + 2  # +2s buffer: int() truncation woke us ~1s before open, tripping the market-closed check below -> daily premature shutdown (signals dead since 2026-04-24)
        log.info(f"Pre-market start — waiting {_wait}s until market opens")
        time.sleep(_wait)

    while running:
        if not is_market_open():
            log.info("Market closed — shutting down")
            notifier.send_shutdown()
            break

        try:
            # Single batch fetch per cycle — engine reads from this same data
            signals = run_evaluation()
            for signal in signals:
                notifier.send_signal(signal)

        except Exception as e:
            log.error(f"Poll cycle error: {e}", exc_info=True)

        interval = int(get_preference("poll_interval", DEFAULT_POLL_INTERVAL))
        time.sleep(interval)

    log.info("Bot stopped")


if __name__ == "__main__":
    run()
