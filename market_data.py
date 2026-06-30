import logging
import math
from datetime import date
import yfinance as yf
from database import get_session, PriceHistory

log = logging.getLogger(__name__)

# Wealthsimple symbols → yfinance tickers
# TSX stocks need .TO suffix, crypto needs -USD suffix
SYMBOL_MAP = {
    "ATZ": "ATZ.TO",
    "BTCC": "BTCC.TO",
    "BTCC.B": "BTCC-B.TO",
    "ETHY.B": "ETHY-B.TO",
    "DIS": "DIS",
    "DFTX": "DFTX",
    "KEEL": "KEEL.TO",
    "MG": "MG.TO",
    "TLRY": "TLRY",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "POL": "POL-USD",
}

# Tickers with no yfinance data (delisted, unlisted, etc.) — skip silently
UNRESOLVABLE = frozenset({"POL-USD"})


def _yf_ticker(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol, symbol)


def fetch_current_price(symbol: str) -> float | None:
    """Single-symbol fetch. Prefer fetch_current_prices() for batch."""
    try:
        ticker = yf.Ticker(_yf_ticker(symbol))
        data = ticker.history(period="1d")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception as e:
        log.error(f"Failed to fetch price for {symbol}: {e}")
        return None


def fetch_current_prices(symbols: list[str]) -> dict[str, float]:
    """Batch fetch via single yf.download call."""
    if not symbols:
        return {}

    yf_tickers = [_yf_ticker(s) for s in symbols if _yf_ticker(s) not in UNRESOLVABLE]
    ws_by_yf = {_yf_ticker(s): s for s in symbols if _yf_ticker(s) not in UNRESOLVABLE}

    try:
        df = yf.download(yf_tickers, period="1d", group_by="ticker", progress=False, threads=True)
        if df.empty:
            return {}
    except Exception as e:
        log.error(f"Batch price fetch failed: {e}")
        return {}

    prices = {}
    if len(yf_tickers) == 1:
        # Single ticker — df columns are just OHLCV, not nested by ticker
        yft = yf_tickers[0]
        ws_sym = ws_by_yf[yft]
        try:
            # group_by="ticker" returns MultiIndex columns even for a single ticker in current yfinance
            series = df[(yft, "Close")] if getattr(df.columns, "nlevels", 1) > 1 else df["Close"]
            close = float(series.iloc[-1])
            if not math.isnan(close):
                prices[ws_sym] = close
        except Exception:
            log.warning(f"No batch price for {ws_sym} ({yft})")
    else:
        for yft in yf_tickers:
            ws_sym = ws_by_yf[yft]
            try:
                close = float(df[(yft, "Close")].iloc[-1])
                if not math.isnan(close):
                    prices[ws_sym] = close
            except Exception:
                log.warning(f"No batch price for {ws_sym} ({yft})")
    return prices


def backfill_history(symbol: str, start_date: str = "2000-01-01") -> int:
    """Fetch all available daily history and store in DB. Returns rows inserted."""
    if _yf_ticker(symbol) in UNRESOLVABLE:
        return 0
    log.info(f"Backfilling {symbol} from {start_date}")
    try:
        ticker = yf.Ticker(_yf_ticker(symbol))
        df = ticker.history(start=start_date, auto_adjust=True)
        if df.empty:
            log.warning(f"No history for {symbol}")
            return 0

        session = get_session()
        count = 0
        try:
            for idx, row in df.iterrows():
                day = idx.date() if hasattr(idx, "date") else idx
                if any(math.isnan(v) for v in [row["Open"], row["High"], row["Low"], row["Close"]]):
                    continue

                exists = session.query(PriceHistory.id).filter_by(symbol=symbol, date=day).first()
                if exists:
                    continue

                session.add(PriceHistory(
                    symbol=symbol,
                    date=day,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                ))
                count += 1

            session.commit()
            log.info(f"Backfilled {count} records for {symbol}")
            return count
        finally:
            session.close()
    except Exception as e:
        log.error(f"Backfill failed for {symbol}: {e}")
        return 0


def update_today(symbol: str) -> bool:
    """Update or insert today's price record."""
    try:
        ticker = yf.Ticker(_yf_ticker(symbol))
        data = ticker.history(period="1d")
        if data.empty:
            return False

        row = data.iloc[-1]
        today = date.today()
        session = get_session()
        try:
            existing = session.query(PriceHistory).filter_by(symbol=symbol, date=today).first()
            if existing:
                existing.close = float(row["Close"])
                existing.high = max(existing.high or 0, float(row["High"]))
                existing.low = min(existing.low or float("inf"), float(row["Low"]))
                existing.volume = int(row["Volume"])
            else:
                session.add(PriceHistory(
                    symbol=symbol, date=today,
                    open=float(row["Open"]), high=float(row["High"]),
                    low=float(row["Low"]), close=float(row["Close"]),
                    volume=int(row["Volume"]),
                ))
            session.commit()
            return True
        finally:
            session.close()
    except Exception as e:
        log.error(f"Failed to update today for {symbol}: {e}")
        return False
