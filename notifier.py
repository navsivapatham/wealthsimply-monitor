import logging
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.configured:
            log.warning("Telegram not configured — skipping notification")
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode},
                timeout=10,
            )
            if not resp.ok:
                log.error(f"Telegram send failed: {resp.text}")
                return False
            return True
        except Exception as e:
            log.error(f"Telegram error: {e}")
            return False

    def send_signal(self, signal: dict) -> bool:
        return self.send_message(signal["message"])

    def send_startup(self, stock_count: int, watchlist_count: int):
        self.send_message(
            f"\U0001f7e2 <b>WealthSimply Monitor started</b>\n"
            f"Tracking {stock_count} holdings, {watchlist_count} watchlist items"
        )

    def send_shutdown(self):
        self.send_message("\U0001f534 <b>WealthSimply Monitor stopped</b> — market closed")
