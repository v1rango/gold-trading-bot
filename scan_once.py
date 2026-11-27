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
import os
import sys
from typing import Optional
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("scanner")

from config import TIMEZONE, START_HOUR, validate_telegram_config
from data.gold import get_gold_price
from data.dashboard_export import refresh_dashboard_from_cache
from strategies.multi_engine import load_state, save_state
from strategies.scan_runner import run_gold_scan
from bot.telegram_bot import TelegramBot, TokenRedactingFilter, redact_secrets
from bot.formatter import format_sleep_message


def _set_github_output(key: str, value: str) -> None:
    out_path = os.getenv("GITHUB_OUTPUT")
    if not out_path:
        return
    try:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    except OSError as e:
        logger.warning(f"Failed to write GITHUB_OUTPUT: {e}")


def should_send_wakeup(state: dict, now: Optional[datetime] = None) -> bool:
    """Return True if wakeup has not yet been sent for today's Tehran date."""
    now = now or datetime.now(TIMEZONE)
    return state.get("last_wakeup_date") != now.strftime("%Y-%m-%d")


def send_sleep_if_needed(
    bot: TelegramBot,
    state: dict,
    now: Optional[datetime] = None,
) -> tuple[bool, bool]:
    """
    Send goodnight message at most once per Tehran date using state.json.
    Returns (sent_sleep_msg, should_deploy_dashboard).
    """
    now = now or datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")

    if state.get("last_sleep_date") == today_str:
        logger.info("Goodnight message already sent today; skipping.")
        changed = False
        try:
            changed = refresh_dashboard_from_cache()
        except Exception:
            pass
        return False, changed

    price = get_gold_price()
    sent = bot.send_message(format_sleep_message(price), reply_markup=bot.get_main_keyboard())
    if sent:
        state["last_sleep_date"] = today_str
        save_state(state)
        logger.info("Goodnight message sent.")
    changed = sent
    try:
        if refresh_dashboard_from_cache(price):
            changed = True
    except Exception as e:
        logger.warning(f"Dashboard refresh warning: {e}")
    return sent, changed


def _run_auto_mode(bot: TelegramBot, now: Optional[datetime] = None) -> bool:
    """Smart Tehran-time handler for external 5-min cron triggers. Returns should_deploy."""
    now = now or datetime.now(TIMEZONE)
    wd = now.weekday()  # Mon=0 .. Fri=4, Sat=5, Sun=6
    state = load_state()

    # 1. Midnight goodnight check (00:00 - 00:25 Tehran, Tue-Sat = end of Mon-Fri sessions)
    if now.hour == 0 and now.minute <= 25 and wd in (1, 2, 3, 4, 5):
        _, should_deploy = send_sleep_if_needed(bot, state, now=now)
        return should_deploy

    # 2. Skip weekends (Sat/Sun) and overnight hours (00:26 - 09:59 Tehran)
    if wd in (5, 6) or now.hour < START_HOUR:
        logger.info(f"Auto-cron: Outside active market window ({now.strftime('%a %H:%M Tehran')}).")
        try:
            return refresh_dashboard_from_cache()
        except Exception:
            return False

    # 3. Morning wakeup check (10:00 - 10:25 Tehran, Mon-Fri)
    send_wakeup = False
    if now.hour == START_HOUR and now.minute <= 25 and should_send_wakeup(state, now=now):
        send_wakeup = True

    run_gold_scan(bot, is_manual=False, send_wakeup_msg=send_wakeup, state=state, now=now)
    return True


def main():
    parser = argparse.ArgumentParser(description="Gold Multi-Engine Market Scanner")
    parser.add_argument("--auto",   action="store_true", help="Smart Tehran-clock mode for external cron")
    parser.add_argument("--manual", action="store_true", help="Manual scan (always reports status)")
    parser.add_argument("--wakeup", action="store_true", help="Send 10:00 AM wakeup message and scan")
    parser.add_argument("--sleep",  action="store_true", help="Send 00:00 AM goodnight message")
    args = parser.parse_args()

    try:
        token, chat_ids = validate_telegram_config()
    except RuntimeError as e:
        logger.critical(str(e))
        sys.exit(1)

    token_filter = TokenRedactingFilter(token)
    for h in logging.getLogger().handlers:
        h.addFilter(token_filter)

    bot = TelegramBot(token, chat_ids)

    if args.sleep:
        logger.info("Sending goodnight message...")
        try:
            state = load_state()
            _, should_deploy = send_sleep_if_needed(bot, state)
            _set_github_output("should_deploy", "true" if should_deploy else "false")
        except Exception as e:
            logger.error(f"Error sending goodnight message: {redact_secrets(e, token)}", exc_info=True)
            sys.exit(1)
        return

    if args.auto:
        logger.info("Running in smart --auto mode...")
        try:
            should_deploy = _run_auto_mode(bot)
            _set_github_output("should_deploy", "true" if should_deploy else "false")
        except Exception as e:
            logger.error(f"Error during auto scan: {redact_secrets(e, token)}", exc_info=True)
            sys.exit(1)
        return

    logger.info("Starting multi-timeframe scan (4H/1H/30M/15M/5M)...")
    try:
        state = load_state()
        send_wakeup = False
        if args.wakeup:
            if should_send_wakeup(state):
                send_wakeup = True
            else:
                logger.info("Wakeup message already sent today; running scan without duplicate wakeup.")
        run_gold_scan(bot, is_manual=args.manual, send_wakeup_msg=send_wakeup, state=state)
        _set_github_output("should_deploy", "true")
    except Exception as e:
        safe_err = redact_secrets(e, token)
        logger.error(f"Error during scan: {safe_err}", exc_info=True)
        if args.manual or args.wakeup:
            bot.send_message(f"⚠️ خطا در اسکن طلا:\n`{safe_err[:200]}`")
        sys.exit(1)


if __name__ == "__main__":
    main()
