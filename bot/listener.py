"""
Telegram Updates Listener (Long-Polling).
Listens for button clicks and commands from the user in real-time.
"""
import time
import requests
import logging
from typing import Callable

logger = logging.getLogger("listener")


def start_listener(token: str, chat_id: str, on_scan_request: Callable, on_summary_request: Callable):
    """
    Continuous polling loop for incoming Telegram buttons and messages.
    Runs in a dedicated background thread.
    """
    base_url = f"https://api.telegram.org/bot{token}"
    offset = None
    logger.info("Telegram interactive listener started... listening for button clicks")

    while True:
        try:
            params = {"timeout": 20}
            if offset is not None:
                params["offset"] = offset

            resp = requests.get(f"{base_url}/getUpdates", params=params, timeout=25)
            if resp.status_code != 200:
                time.sleep(2)
                continue

            data = resp.json()
            if not data.get("ok"):
                time.sleep(2)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                # 1. Handle Inline Button Click
                if "callback_query" in update:
                    cb = update["callback_query"]
                    cb_id = cb.get("id")
                    data_val = cb.get("data")
                    
                    # Acknowledge button click
                    try:
                        requests.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "در حال اسکن بازار..."})
                    except Exception:
                        pass

                    if data_val == "scan_now":
                        on_scan_request(is_manual=True)

                # 2. Handle Text Messages & Bottom Keyboard Buttons
                elif "message" in update:
                    msg = update["message"]
                    sender_id = str(msg.get("chat", {}).get("id"))
                    text = msg.get("text", "").strip()

                    # Only respond to the authorized chat ID
                    if sender_id != chat_id:
                        continue

                    if text in ("🔍 همین الان اسکن کن (طلا)", "/scan", "اسکن"):
                        logger.info("Received manual scan request via Telegram button/text")
                        on_scan_request(is_manual=True)
                    elif text in ("📊 خلاصه وضعیت بازار", "/summary"):
                        logger.info("Received summary request via Telegram button")
                        on_summary_request()
                    elif text in ("/start", "ℹ️ راهنما", "/help"):
                        welcome_text = (
                            "👋 *به ربات سیگنال طلا خوش آمدید!*\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            "این ربات هر ۱۰ دقیقه بازار طلا را با ۸ اندیکاتور تکنیکال دقیق اسکن می‌کند.\n\n"
                            "🔘 *دکمه‌های اختصاصی:*\n"
                            "• با زدن دکمه *«🔍 همین الان اسکن کن (طلا)»* در پایین صفحه، وضعیت لحظه‌ای طلا و سیگنال فوری دریافت می‌کنید.\n"
                            "• با زدن *«📊 خلاصه وضعیت بازار»* تغییرات ۲۴ ساعته و اخبار طلا را می‌بینید."
                        )
                        payload = {
                            "chat_id": chat_id,
                            "text": welcome_text,
                            "parse_mode": "Markdown",
                            "reply_markup": {
                                "keyboard": [
                                    [{"text": "🔍 همین الان اسکن کن (طلا)"}],
                                    [{"text": "📊 خلاصه وضعیت بازار"}, {"text": "ℹ️ راهنما"}]
                                ],
                                "resize_keyboard": True,
                                "persistent": True
                            }
                        }
                        requests.post(f"{base_url}/sendMessage", json=payload, timeout=10)

        except Exception as e:
            logger.warning(f"Listener error (will retry): {e}")
            time.sleep(3)
