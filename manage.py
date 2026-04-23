import argparse
import sys
from database import init_db, get_session, set_preference, get_preference, Stock, Signal
from market_data import backfill_history


def cmd_sync(args):
    from api_client import SnapTradeClient
    from bot import sync_holdings
    init_db()
    sync_holdings(SnapTradeClient())
    print("Holdings synced from Wealthsimple.")


def cmd_watch(args):
    init_db()
    symbol = args.symbol.upper()
    session = get_session()
    try:
        existing = session.query(Stock).filter_by(symbol=symbol).first()
        if existing:
            existing.is_watchlist = True
            if args.target:
                existing.target_price = args.target
            if args.threshold:
                existing.sma_threshold = args.threshold
            print(f"Updated {symbol} on watchlist")
        else:
            session.add(Stock(
                symbol=symbol,
                source="manual",
                is_watchlist=True,
                target_price=args.target,
                sma_threshold=args.threshold or 5.0,
            ))
            print(f"Added {symbol} to watchlist")
        session.commit()
    finally:
        session.close()

    print(f"Backfilling historical data for {symbol}...")
    count = backfill_history(symbol)
    print(f"  {count} records loaded")


def cmd_unwatch(args):
    init_db()
    symbol = args.symbol.upper()
    session = get_session()
    try:
        stock = session.query(Stock).filter_by(symbol=symbol).first()
        if not stock:
            print(f"{symbol} not found")
            return
        if stock.source == "manual" and (stock.shares or 0) == 0:
            session.delete(stock)
            print(f"Removed {symbol}")
        else:
            stock.is_watchlist = False
            stock.target_price = None
            print(f"Removed {symbol} from watchlist (still tracked as holding)")
        session.commit()
    finally:
        session.close()


def cmd_add(args):
    init_db()
    symbol = args.symbol.upper()
    session = get_session()
    try:
        existing = session.query(Stock).filter_by(symbol=symbol).first()
        if existing:
            old_shares = existing.shares or 0
            new_total = old_shares + args.shares
            if args.cost and new_total > 0:
                old_value = (existing.average_cost or 0) * old_shares
                existing.average_cost = (old_value + args.cost * args.shares) / new_total
            existing.shares = new_total
            if existing.source == "wealthsimple":
                existing.source = "manual"
            print(f"Updated {symbol}: {existing.shares:.2f} shares @ ${existing.average_cost:.2f}")
        else:
            session.add(Stock(
                symbol=symbol,
                shares=args.shares,
                average_cost=args.cost,
                source="manual",
            ))
            print(f"Added {symbol}: {args.shares} shares @ ${args.cost:.2f}")
        session.commit()
    finally:
        session.close()

    print(f"Backfilling historical data for {symbol}...")
    count = backfill_history(symbol)
    print(f"  {count} records loaded")


def cmd_status(args):
    init_db()
    session = get_session()
    try:
        holdings = session.query(Stock).filter(Stock.shares > 0).order_by(Stock.symbol).all()
        watchlist = session.query(Stock).filter_by(is_watchlist=True).order_by(Stock.symbol).all()
        pending = session.query(Signal).filter_by(status="pending").order_by(Signal.timestamp.desc()).limit(10).all()

        print(f"\n{'=' * 60}")
        print(f" HOLDINGS ({len(holdings)})")
        print(f"{'=' * 60}")
        for s in holdings:
            target = f"  target: ${s.target_price:.2f}" if s.target_price else ""
            print(f"  {s.symbol:<8} {s.shares:>10.2f} shares @ ${s.average_cost or 0:>8.2f}  [{s.source}]{target}")

        print(f"\n{'=' * 60}")
        print(f" WATCHLIST ({len(watchlist)})")
        print(f"{'=' * 60}")
        for s in watchlist:
            trigger = f"target: ${s.target_price:.2f}" if s.target_price else f"SMA threshold: {s.sma_threshold}%"
            print(f"  {s.symbol:<8} {trigger}")

        if pending:
            print(f"\n{'=' * 60}")
            print(f" PENDING SIGNALS ({len(pending)})")
            print(f"{'=' * 60}")
            for s in pending:
                print(f"  [{s.timestamp:%Y-%m-%d %H:%M}] {s.message}")

        print(f"\nPoll interval: {get_preference('poll_interval', '60')}s")
    finally:
        session.close()


def cmd_set(args):
    init_db()
    set_preference(args.key, args.value)
    print(f"Set {args.key} = {args.value}")


def cmd_backfill(args):
    init_db()
    session = get_session()
    try:
        if args.symbol:
            symbols = [args.symbol.upper()]
        else:
            symbols = [s.symbol for s in session.query(Stock).all()]
    finally:
        session.close()

    for symbol in symbols:
        print(f"Backfilling {symbol}...")
        count = backfill_history(symbol)
        print(f"  {count} records")


def main():
    parser = argparse.ArgumentParser(description="WealthSimply Monitor")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("sync", help="Sync holdings from Wealthsimple")
    sub.add_parser("status", help="Show current state")

    p = sub.add_parser("watch", help="Add symbol to watchlist")
    p.add_argument("symbol")
    p.add_argument("--target", type=float, help="Target buy price")
    p.add_argument("--threshold", type=float, help="Pct below SMA to trigger (default 5)")

    p = sub.add_parser("unwatch", help="Remove from watchlist")
    p.add_argument("symbol")

    p = sub.add_parser("add", help="Add manual holding")
    p.add_argument("symbol")
    p.add_argument("shares", type=float)
    p.add_argument("--cost", type=float, help="Average cost per share")

    p = sub.add_parser("set", help="Set preference (e.g. poll_interval 120)")
    p.add_argument("key")
    p.add_argument("value")

    p = sub.add_parser("backfill", help="Backfill price history")
    p.add_argument("symbol", nargs="?", help="Symbol, or omit for all")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmds = {
        "sync": cmd_sync, "status": cmd_status, "watch": cmd_watch,
        "unwatch": cmd_unwatch, "add": cmd_add, "set": cmd_set, "backfill": cmd_backfill,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
