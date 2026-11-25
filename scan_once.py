"""
Scan Gold once — executed by GitHub Actions (every 5 min or manual trigger).
Runs the 4-timeframe portfolio (1H + 30M + 15M + 5M) via shared scan_runner.
"""
import argparse
import logging
import sys
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("scanner")

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
from data.gold import get_gold_price
from strategies.scan_runner import run_gold_scan
from bot.telegram_bot import TelegramBot
from bot.formatter import format_sleep_message


def main():
    parser = argparse.ArgumentParser(description="Gold Multi-Engine Market Scanner")
    parser.add_argument("--manual", action="store_true", help="Manual scan (always reports status)")
    parser.add_argument("--wakeup", action="store_true", help="Send 10:00 AM wakeup message and scan")
    parser.add_argument("--sleep",  action="store_true", help="Send 00:00 AM goodnight message")
    args = parser.parse_args()

    bot = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS)

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

    logger.info("Starting multi-timeframe scan (4H/1H/30M/15M/5M)...")
    try:
        run_gold_scan(bot, is_manual=args.manual, send_wakeup_msg=args.wakeup)
    except Exception as e:
        logger.error(f"Error during scan: {e}", exc_info=True)
        if args.manual or args.wakeup:
            bot.send_message(f"⚠️ خطا در اسکن طلا:\n`{str(e)[:200]}`")
        sys.exit(1)


if __name__ == "__main__":
    main()
