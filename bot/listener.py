"""
Telegram Updates Listener (Long-Polling).
Listens for button clicks and commands from the user in real-time.
"""
import time
import requests
import logging
from typing import Callable, Union, List


logger = logging.getLogger("listener")


def start_listener(token: str, chat_ids: Union[str, List[str]],
                   on_scan_request: Callable, on_summary_request: Callable):
    """
    Continuous polling loop for incoming Telegram buttons and messages.
    Runs in a dedicated background thread and supports multiple authorized users.
    """
    allowed_ids = (
        {c.strip() for c in chat_ids.split(",") if c.strip()}
        if isinstance(chat_ids, str)
        else {str(c).strip() for c in chat_ids if str(c).strip()}
    )
    base_url = f"https://api.telegram.org/bot{token}"
    offset = None
    logger.info(f"Telegram interactive listener started for chats {sorted(allowed_ids)}")

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
                    sender_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))

                    if sender_id not in allowed_ids:
                        continue

                    try:
                        requests.post(f"{base_url}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "در حال اسکن بازار..."})
                    except Exception:
                        pass

                    if data_val == "scan_now":
                        on_scan_request(is_manual=True, target_chat_id=sender_id)

                # 2. Handle Text Messages & Bottom Keyboard Buttons
                elif "message" in update:
                    msg = update["message"]
                    sender_id = str(msg.get("chat", {}).get("id"))
                    text = msg.get("text", "").strip()

                    if sender_id not in allowed_ids:
                        continue

                    if text in ("🔍 همین الان اسکن کن (طلا)", "/scan", "اسکن"):
                        logger.info(f"Received manual scan request from {sender_id}")
                        on_scan_request(is_manual=True, target_chat_id=sender_id)
                    elif text in ("📊 خلاصه وضعیت بازار", "/summary"):
                        logger.info(f"Received summary request from {sender_id}")
                        on_summary_request(target_chat_id=sender_id)
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
                            "chat_id": sender_id,
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
