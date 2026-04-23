from flask import Flask, jsonify, request, send_from_directory
from datetime import datetime
from database import init_db, get_session, Stock, PriceHistory, PollingLog, Signal, get_preference
from engine import _calc_sma
from market_data import backfill_history, fetch_current_prices

app = Flask(__name__, static_folder="static")


@app.route("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")


@app.route("/api/holdings")
def api_holdings():
    session = get_session()
    try:
        stocks = session.query(Stock).filter(Stock.shares > 0).order_by(Stock.symbol).all()
        holdings = []

        for s in stocks:
            latest = (
                session.query(PollingLog)
                .filter(PollingLog.symbol == s.symbol)
                .order_by(PollingLog.timestamp.desc())
                .first()
            )
            current_price = latest.current_price if latest else None
            sma_50 = latest.sma_50 if latest else _calc_sma(session, s.symbol, 50)
            dist_sma = latest.distance_from_sma_50 if latest else None

            if current_price is None:
                ph = (
                    session.query(PriceHistory)
                    .filter(PriceHistory.symbol == s.symbol)
                    .order_by(PriceHistory.date.desc())
                    .first()
                )
                current_price = ph.close if ph else 0

            holdings.append({
                "symbol": s.symbol,
                "company_name": s.company_name or "",
                "shares": s.shares,
                "average_cost": s.average_cost or 0,
                "current_price": current_price or 0,
                "sma_50": round(sma_50, 2) if sma_50 else None,
                "distance_from_sma": round(dist_sma, 2) if dist_sma else None,
                "source": s.source,
            })

        watchlist_count = session.query(Stock).filter_by(is_watchlist=True).count()
        pending_signals = session.query(Signal).filter_by(status="pending").count()

        return jsonify({
            "holdings": holdings,
            "summary": {
                "positions_count": len(holdings),
                "watchlist_count": watchlist_count,
                "pending_signals": pending_signals,
            },
        })
    finally:
        session.close()


@app.route("/api/watchlist")
def api_watchlist():
    session = get_session()
    try:
        stocks = session.query(Stock).filter_by(is_watchlist=True).order_by(Stock.symbol).all()
        items = []
        for s in stocks:
            latest = (
                session.query(PollingLog)
                .filter(PollingLog.symbol == s.symbol)
                .order_by(PollingLog.timestamp.desc())
                .first()
            )
            items.append({
                "symbol": s.symbol,
                "company_name": s.company_name or "",
                "target_price": s.target_price,
                "sma_threshold": s.sma_threshold or 5.0,
                "current_price": latest.current_price if latest else None,
                "sma_50": round(latest.sma_50, 2) if latest and latest.sma_50 else None,
                "distance_from_sma": round(latest.distance_from_sma_50, 2) if latest and latest.distance_from_sma_50 else None,
            })
        return jsonify({"watchlist": items})
    finally:
        session.close()


@app.route("/api/watchlist/add", methods=["POST"])
def api_watchlist_add():
    data = request.json or {}
    symbol = (data.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    target_price = data.get("target_price")
    threshold = data.get("sma_threshold", 5.0)

    session = get_session()
    try:
        existing = session.query(Stock).filter_by(symbol=symbol).first()
        if existing:
            existing.is_watchlist = True
            if target_price is not None:
                existing.target_price = float(target_price)
            existing.sma_threshold = float(threshold)
        else:
            session.add(Stock(
                symbol=symbol,
                source="manual",
                is_watchlist=True,
                target_price=float(target_price) if target_price else None,
                sma_threshold=float(threshold),
            ))
        session.commit()
    finally:
        session.close()

    backfill_history(symbol)
    return jsonify({"ok": True, "symbol": symbol})


@app.route("/api/watchlist/remove", methods=["POST"])
def api_watchlist_remove():
    data = request.json or {}
    symbol = (data.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    session = get_session()
    try:
        stock = session.query(Stock).filter_by(symbol=symbol).first()
        if not stock:
            return jsonify({"error": "Not found"}), 404
        if stock.source == "manual" and (stock.shares or 0) == 0:
            session.delete(stock)
        else:
            stock.is_watchlist = False
            stock.target_price = None
        session.commit()
    finally:
        session.close()
    return jsonify({"ok": True, "symbol": symbol})


@app.route("/api/watchlist/refresh", methods=["POST"])
def api_watchlist_refresh():
    """Fetch fresh prices for all watchlist items."""
    session = get_session()
    try:
        stocks = session.query(Stock).filter_by(is_watchlist=True).all()
        symbols = [s.symbol for s in stocks]
    finally:
        session.close()

    if not symbols:
        return jsonify({"ok": True, "refreshed": 0})

    prices = fetch_current_prices(symbols)
    return jsonify({"ok": True, "refreshed": len(prices), "prices": prices})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Trigger a full holdings sync from SnapTrade."""
    from api_client import SnapTradeClient
    from bot import sync_holdings
    try:
        sync_holdings(SnapTradeClient())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/signals")
def api_signals():
    session = get_session()
    try:
        signals = (
            session.query(Signal)
            .order_by(Signal.timestamp.desc())
            .limit(50)
            .all()
        )
        return jsonify({
            "signals": [
                {
                    "id": s.id,
                    "symbol": s.symbol,
                    "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                    "signal_type": s.signal_type,
                    "current_price": s.current_price,
                    "trigger_value": s.trigger_value,
                    "message": s.message,
                    "status": s.status,
                }
                for s in signals
            ],
            "pending_count": sum(1 for s in signals if s.status == "pending"),
        })
    finally:
        session.close()


@app.route("/api/chart/<symbol>")
def api_chart(symbol):
    session = get_session()
    try:
        records = (
            session.query(PriceHistory)
            .filter(PriceHistory.symbol == symbol.upper())
            .order_by(PriceHistory.date.desc())
            .limit(90)
            .all()
        )
        records.reverse()
        return jsonify({
            "symbol": symbol.upper(),
            "prices": [
                {"date": r.date.isoformat(), "close": r.close}
                for r in records
            ],
        })
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=False)
