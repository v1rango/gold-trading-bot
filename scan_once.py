"""
Scan Gold once — executed by GitHub Actions (via cron-job.org or manual trigger).
Supports:
  --auto   : Smart Tehran-clock mode (wakeup 10:00, scan 10:00-23:59, sleep 00:00, skip weekends)
  --manual : Immediate manual scan (always reports status)
  --wakeup : Force wakeup message + scan
  --sleep  : Force goodnight message
"""
import argparse
from datetime import datetime
import logging
import sys
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("scanner")

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, TIMEZONE, START_HOUR
from data.gold import get_gold_price
from data.dashboard_export import refresh_dashboard_from_cache
from strategies.multi_engine import load_state, save_state
from strategies.scan_runner import run_gold_scan
from bot.telegram_bot import TelegramBot
from bot.formatter import format_sleep_message


def _run_auto_mode(bot: TelegramBot) -> None:
    """Smart Tehran-time handler for external 5-min cron triggers."""
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    wd = now.weekday()  # Mon=0 .. Fri=4, Sat=5, Sun=6
    state = load_state()

    # 1. Midnight goodnight check (00:00 - 00:25 Tehran, Tue-Sat = end of Mon-Fri sessions)
    if now.hour == 0 and now.minute <= 25 and wd in (1, 2, 3, 4, 5):
        if state.get("last_sleep_date") != today_str:
            price = get_gold_price()
            bot.send_message(format_sleep_message(price), reply_markup=bot.get_main_keyboard())
            state["last_sleep_date"] = today_str
            save_state(state)
            try:
                refresh_dashboard_from_cache(price)
            except Exception as e:
                logger.warning(f"Dashboard refresh warning: {e}")
            logger.info("Auto-cron: Goodnight message sent.")
        else:
            logger.info("Auto-cron: Goodnight already sent today; outside active hours.")
            try:
                refresh_dashboard_from_cache()
            except Exception:
                pass
        return

    # 2. Skip weekends (Sat/Sun) and overnight hours (00:26 - 09:59 Tehran)
    if wd in (5, 6) or now.hour < START_HOUR:
        logger.info(f"Auto-cron: Outside active market window ({now.strftime('%a %H:%M Tehran')}).")
        try:
            refresh_dashboard_from_cache()
        except Exception:
            pass
        return

    # 3. Morning wakeup check (10:00 - 10:25 Tehran, Mon-Fri)
    send_wakeup = False
    if now.hour == START_HOUR and now.minute <= 25 and state.get("last_wakeup_date") != today_str:
        send_wakeup = True
        state["last_wakeup_date"] = today_str

    run_gold_scan(bot, is_manual=False, send_wakeup_msg=send_wakeup, state=state)


def main():
    parser = argparse.ArgumentParser(description="Gold Multi-Engine Market Scanner")
    parser.add_argument("--auto",   action="store_true", help="Smart Tehran-clock mode for external cron")
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

    if args.auto:
        logger.info("Running in smart --auto mode...")
        try:
            _run_auto_mode(bot)
        except Exception as e:
            logger.error(f"Error during auto scan: {e}", exc_info=True)
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
