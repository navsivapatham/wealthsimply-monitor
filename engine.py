import logging
from datetime import datetime
from database import get_session, Stock, PriceHistory, PollingLog, Signal
from market_data import fetch_current_prices
from config import DEFAULT_SMA_PERIOD, DEFAULT_SMA_THRESHOLD

log = logging.getLogger(__name__)


def _calc_sma(session, symbol: str, period: int) -> float | None:
    records = (
        session.query(PriceHistory.close)
        .filter(PriceHistory.symbol == symbol, PriceHistory.close.isnot(None))
        .order_by(PriceHistory.date.desc())
        .limit(period)
        .all()
    )
    if len(records) < period:
        return None
    return sum(r.close for r in records) / period


def _pct_distance(current: float, reference: float) -> float:
    return ((current - reference) / reference) * 100


def _evaluate(session, stock: Stock, current_price: float) -> dict | None:
    sma_50 = _calc_sma(session, stock.symbol, 50)
    sma_200 = _calc_sma(session, stock.symbol, 200)
    threshold = stock.sma_threshold or DEFAULT_SMA_THRESHOLD

    dist_sma = _pct_distance(current_price, sma_50) if sma_50 else None
    dist_avg = _pct_distance(current_price, stock.average_cost) if stock.average_cost else None

    log_entry = PollingLog(
        symbol=stock.symbol,
        current_price=current_price,
        sma_50=sma_50,
        sma_200=sma_200,
        distance_from_sma_50=dist_sma,
        distance_from_avg_cost=dist_avg,
    )

    signal_data = None

    # Target price trigger (watchlist items)
    if stock.target_price and current_price <= stock.target_price:
        msg = (
            f"\U0001f3af {stock.symbol} hit target ${stock.target_price:.2f} "
            f"(now ${current_price:.2f})"
        )
        signal_data = {"symbol": stock.symbol, "type": "target_price", "message": msg}
        session.add(Signal(
            symbol=stock.symbol, signal_type="target_price",
            current_price=current_price, trigger_value=stock.target_price,
            message=msg,
        ))
        log_entry.signal = "buy"

    # SMA signal — price fell below threshold % of 50-day SMA
    elif sma_50 and dist_sma is not None and dist_sma <= -threshold:
        msg = (
            f"\U0001f4c9 {stock.symbol} is {abs(dist_sma):.1f}% below 50-day SMA "
            f"(${sma_50:.2f}). Now: ${current_price:.2f}"
        )
        signal_data = {"symbol": stock.symbol, "type": "sma_cross", "message": msg}
        session.add(Signal(
            symbol=stock.symbol, signal_type="sma_cross",
            current_price=current_price, trigger_value=sma_50,
            message=msg,
        ))
        log_entry.signal = "buy"

    session.add(log_entry)
    return signal_data


def run_evaluation() -> list[dict]:
    """Evaluate all tracked stocks via single batch price fetch."""
    session = get_session()
    try:
        stocks = session.query(Stock).filter(
            (Stock.is_watchlist == True) | (Stock.shares > 0)
        ).all()

        symbols = [s.symbol for s in stocks]
        prices = fetch_current_prices(symbols)
        log.info(f"Batch fetched {len(prices)}/{len(symbols)} prices")

        signals = []
        for stock in stocks:
            price = prices.get(stock.symbol)
            if price is None:
                log.warning(f"No price for {stock.symbol}, skipping")
                continue

            signal = _evaluate(session, stock, price)
            if signal:
                signals.append(signal)
                log.info(f"SIGNAL: {signal['message']}")

        session.commit()
        return signals
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
