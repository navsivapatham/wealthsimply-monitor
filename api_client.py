import time
import logging
from functools import wraps
from snaptrade_client import SnapTrade, ApiException
from config import (
    SNAPTRADE_CLIENT_ID, SNAPTRADE_CONSUMER_KEY,
    SNAPTRADE_USER_ID, SNAPTRADE_USER_SECRET,
)

log = logging.getLogger(__name__)


def retry_with_backoff(max_retries=3):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except ApiException as e:
                    if e.status == 429 and attempt < max_retries - 1:
                        reset = int(getattr(e, "headers", {}).get("X-RateLimit-Reset", 10))
                        wait = reset + (2 ** attempt)
                        log.warning(f"Rate limited. Waiting {wait}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait)
                    else:
                        raise
        return wrapper
    return decorator


class SnapTradeClient:
    def __init__(self):
        self.client = SnapTrade(
            consumer_key=SNAPTRADE_CONSUMER_KEY,
            client_id=SNAPTRADE_CLIENT_ID,
        )
        self.user_id = SNAPTRADE_USER_ID
        self.user_secret = SNAPTRADE_USER_SECRET

    def _attr(self, obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @retry_with_backoff()
    def list_accounts(self):
        response = self.client.account_information.list_user_accounts(
            user_id=self.user_id,
            user_secret=self.user_secret,
        )
        return response.body

    @retry_with_backoff()
    def get_positions(self, account_id: str):
        response = self.client.account_information.get_user_account_positions(
            account_id=account_id,
            user_id=self.user_id,
            user_secret=self.user_secret,
        )
        return response.body

    @retry_with_backoff()
    def list_connections(self):
        response = self.client.connections.list_brokerage_authorizations(
            user_id=self.user_id,
            user_secret=self.user_secret,
        )
        return response.body

    @retry_with_backoff()
    def refresh_connection(self, authorization_id: str):
        """Trigger manual data refresh. Async — data isn't immediately fresh. Costs extra."""
        response = self.client.connections.refresh_brokerage_authorization(
            authorization_id=authorization_id,
            user_id=self.user_id,
            user_secret=self.user_secret,
        )
        return response.body

    def _normalize_position(self, pos, account_id: str, account_name: str) -> dict:
        # SDK nests: pos["symbol"]["symbol"] → UniversalSymbol dict with ticker at ["symbol"]
        pos_symbol = self._attr(pos, "symbol") or {}
        universal = self._attr(pos_symbol, "symbol") or {}
        ticker = self._attr(universal, "raw_symbol") or self._attr(universal, "symbol")
        description = self._attr(universal, "description") or self._attr(pos_symbol, "description") or ""

        # Ensure we extracted strings, not more nested dicts
        if isinstance(ticker, dict):
            ticker = ticker.get("raw_symbol") or ticker.get("symbol")
        if isinstance(description, dict):
            description = ""

        return {
            "symbol": ticker,
            "company_name": description,
            "units": float(self._attr(pos, "units") or 0),
            "average_purchase_price": float(self._attr(pos, "average_purchase_price") or 0),
            "current_price": float(self._attr(pos, "price") or 0),
            "account_id": account_id,
            "account_name": account_name,
        }

    def get_all_holdings(self) -> list[dict]:
        """Fetch positions across all accounts, normalized to dicts."""
        accounts = self.list_accounts()
        all_positions = []

        for account in accounts:
            account_id = str(self._attr(account, "id", ""))
            account_name = self._attr(account, "name", "Unknown")
            if not account_id:
                continue
            try:
                positions = self.get_positions(account_id)
                for pos in positions:
                    normalized = self._normalize_position(pos, account_id, account_name)
                    if normalized["symbol"]:
                        all_positions.append(normalized)
            except ApiException as e:
                log.error(f"Failed to fetch positions for {account_name}: {e}")

        return all_positions
