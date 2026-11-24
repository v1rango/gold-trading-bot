import requests
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token    = token
        self.chat_id  = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def get_main_keyboard(self) -> Dict[str, Any]:
        """Persistent bottom keyboard with scan button."""
        return {
            "keyboard": [
                [{"text": "🔍 همین الان اسکن کن (طلا)"}],
                [{"text": "📊 خلاصه وضعیت بازار"}, {"text": "ℹ️ راهنما"}]
            ],
            "resize_keyboard": True,
            "persistent": True
        }

    def get_scan_inline_keyboard(self) -> Dict[str, Any]:
        """Inline button under messages for quick re-scan."""
        return {
            "inline_keyboard": [
                [{"text": "🔄 اسکن مجدد لحظه‌ای", "callback_data": "scan_now"}]
            ]
        }

    def send_message(self, text: str, parse_mode: str = "Markdown",
                     reply_markup: Optional[Dict[str, Any]] = None) -> bool:
        """Send a text message to the configured chat with retry fallback."""
        payload = {
            "chat_id":                  self.chat_id,
            "text":                     text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        else:
            payload["reply_markup"] = self.get_main_keyboard()

        try:
            resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
            resp.raise_for_status()
            logger.info("Telegram message sent ✅")
            return True
        except Exception as e:
            logger.warning(f"Telegram send failed with {parse_mode}: {e}. Retrying without formatting...")
            if parse_mode is not None:
                try:
                    payload.pop("parse_mode", None)
                    payload["text"] = text.replace("*", "").replace("`", "").replace("_", "")
                    resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
                    resp.raise_for_status()
                    logger.info("Telegram message sent via plain text fallback ✅")
                    return True
                except Exception as e2:
                    logger.error(f"Telegram fallback retry failed: {e2}")
            logger.error(f"Telegram send error: {e}")
            return False

    def test_connection(self) -> bool:
        """Verify bot token is valid."""
        try:
            resp = requests.get(f"{self.base_url}/getMe", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
