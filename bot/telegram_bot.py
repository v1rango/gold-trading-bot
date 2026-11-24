import requests
import logging

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token    = token
        self.chat_id  = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a text message to the configured chat with retry fallback."""
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id":                  self.chat_id,
                    "text":                     text,
                    "parse_mode":               parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("Telegram message sent ✅")
            return True
        except Exception as e:
            logger.warning(f"Telegram send failed with {parse_mode}: {e}. Retrying without formatting...")
            if parse_mode is not None:
                try:
                    # Clean markdown symbols for fallback
                    clean_text = text.replace("*", "").replace("`", "").replace("_", "")
                    resp = requests.post(
                        f"{self.base_url}/sendMessage",
                        json={
                            "chat_id":                  self.chat_id,
                            "text":                     clean_text,
                            "disable_web_page_preview": True,
                        },
                        timeout=15,
                    )
                    resp.raise_for_status()
                    logger.info("Telegram message sent via plain text fallback ✅")
                    return True
                except Exception as e2:
                    logger.error(f"Telegram fallback retry also failed: {e2}")
            logger.error(f"Telegram send error: {e}")
            return False

    def test_connection(self) -> bool:
        """Verify bot token is valid."""
        try:
            resp = requests.get(f"{self.base_url}/getMe", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
