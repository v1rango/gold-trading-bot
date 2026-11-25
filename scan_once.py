"""
Scan Gold once — executed by GitHub Actions (every 10 min or manual trigger).
Exits immediately after scanning.
"""
import sys
import argparse
import logging
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("scanner")

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
from data.gold import get_gold_4h, get_gold_1h, get_gold_30m, get_gold_price
from strategies.indicators import calculate_indicators
from strategies.signals import generate_signal
from bot.telegram_bot import TelegramBot
from bot.formatter import (
    format_signal, format_manual_status,
    format_wakeup_message, format_sleep_message,
)


def main():
    parser = argparse.ArgumentParser(description="Gold Market Scanner")
    parser.add_argument("--manual", action="store_true", help="Manual scan (always reports status)")
    parser.add_argument("--wakeup", action="store_true", help="Send 12:00 PM wakeup message and scan")
    parser.add_argument("--sleep",  action="store_true", help="Send 00:00 AM goodnight message")
    args = parser.parse_args()

    bot = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS)

    # ── Goodnight mode (00:00 Tehran) ─────────────────────────────────────────
    if args.sleep:
        logger.info("Sending goodnight message...")
        try:
            price = get_gold_price()
            bot.send_message(format_sleep_message(price), reply_markup=bot.get_main_keyboard())
            logger.info("Goodnight message sent.")
        except Exception as e:
            logger.error(f"Error sending goodnight message: {e}", exc_info=True)
            sys.exit(1)
        return

    logger.info("Starting single scan...")
    try:
        df4h  = calculate_indicators(get_gold_4h())
        df1h  = calculate_indicators(get_gold_1h())
        df30m = calculate_indicators(get_gold_30m())
        price = get_gold_price()

        # ── Wakeup mode (12:00 Tehran) ────────────────────────────────────────
        if args.wakeup:
            bot.send_message(
                format_wakeup_message(price, df1h.iloc[-1]),
                reply_markup=bot.get_main_keyboard(),
            )
            logger.info("Wakeup message sent.")

        sig = generate_signal(df4h, df1h, df30m, current_price=price["price"])

        # 1. If valid signal found -> send full signal
        if sig.direction in ("BUY", "SELL"):
            logger.info(f"Signal found: {sig.direction} at {sig.entry}")
            msg = format_signal(sig, price)
            bot.send_message(msg, reply_markup=bot.get_scan_inline_keyboard())
            return

        # 2. If manual scan requested -> notify user of market status
        if args.manual:
            status_msg = format_manual_status(price, df1h.iloc[-1], sig.skip_reason)
            bot.send_message(status_msg, reply_markup=bot.get_scan_inline_keyboard())
            logger.info("Manual scan status sent to Telegram.")
        else:
            logger.info(f"Scan finished silently: {sig.skip_reason}")

    except Exception as e:
        logger.error(f"Error during scan: {e}", exc_info=True)
        if args.manual or args.wakeup:
            bot.send_message(f"⚠️ خطا در اسکن طلا:\n`{str(e)[:200]}`")
        sys.exit(1)


if __name__ == "__main__":
    main()
