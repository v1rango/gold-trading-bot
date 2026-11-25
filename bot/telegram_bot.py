import requests
import logging
from typing import Optional, Dict, Any, Union, List

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, chat_ids: Union[str, List[str]]):
        self.token = token
        if isinstance(chat_ids, str):
            self.chat_ids = [c.strip() for c in chat_ids.split(",") if c.strip()]
        else:
            self.chat_ids = [str(c).strip() for c in chat_ids if str(c).strip()]
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

    def _send_to_chat(self, chat_id: str, text: str, parse_mode: Optional[str],
                      reply_markup: Dict[str, Any]) -> bool:
        """Send a message to a single Telegram chat ID with plain-text retry fallback."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
            if resp.status_code == 200:
                logger.info(f"Telegram message sent to {chat_id} ✅")
                return True
            err_body = resp.text
            logger.warning(f"Telegram send to {chat_id} failed ({resp.status_code}): {err_body}")
            if parse_mode is not None and resp.status_code == 400 and "parse entities" in err_body.lower():
                payload.pop("parse_mode", None)
                payload["text"] = text.replace("*", "").replace("`", "").replace("_", "")
                resp2 = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
                if resp2.status_code == 200:
                    logger.info(f"Telegram plain fallback sent to {chat_id} ✅")
                    return True
                logger.error(f"Telegram fallback to {chat_id} also failed: {resp2.text}")
            return False
        except Exception as e:
            logger.error(f"Telegram request error for {chat_id}: {e}")
            return False

    def send_message(self, text: str, parse_mode: str = "Markdown",
                     reply_markup: Optional[Dict[str, Any]] = None,
                     chat_id: Optional[str] = None) -> bool:
        """Send a message to one specific chat_id or broadcast to all configured chat_ids."""
        markup = reply_markup or self.get_main_keyboard()
        targets = [str(chat_id)] if chat_id else self.chat_ids
        results = [self._send_to_chat(cid, text, parse_mode, markup) for cid in targets]
        return any(results)

    def test_connection(self) -> bool:
        """Verify bot token is valid."""
        try:
            resp = requests.get(f"{self.base_url}/getMe", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
