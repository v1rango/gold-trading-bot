"""
Gold Trading Bot — Main Entry Point
Monitors XAU/USD (OANDA Spot) across 4H / 1H / 30M / 15M / 5M timeframes.
Active hours: 10:00 AM – 00:00 AM Tehran time (scan every 5 min).
"""
import logging
import sys
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
from data.gold import get_gold_1h, get_gold_4h, get_gold_price
from data.news import fetch_news
from strategies.indicators import calculate_indicators
from strategies.multi_engine import get_htf_bias
from strategies.scan_runner import run_gold_scan
from bot.telegram_bot import TelegramBot
from bot.formatter import (
    format_daily_summary, format_startup,
    format_wakeup_message, format_sleep_message,
)
from bot.listener import start_listener
from scheduler.runner import setup_scheduler

bot = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS)


def scan_gold(is_manual: bool = False, target_chat_id: str | None = None) -> None:
    logger.info("=" * 55)
    logger.info(f"Gold scan started (manual={is_manual}) …")
    try:
        run_gold_scan(bot, is_manual=is_manual, target_chat_id=target_chat_id)
    except Exception as exc:
        logger.error(f"Scan error: {exc}", exc_info=True)
        if is_manual:
            bot.send_message(f"⚠️ خطا در اسکن طلا:\n`{str(exc)[:200]}`", chat_id=target_chat_id)


def daily_summary(target_chat_id: str | None = None) -> None:
    try:
        price = get_gold_price()
        news  = fetch_news()
        gold_news = [n for n in news if n["type"] == "GOLD"] or news[:3]
        bot.send_message(format_daily_summary(price, gold_news), chat_id=target_chat_id)
        logger.info("Daily summary sent.")
    except Exception as exc:
        logger.error(f"Daily summary error: {exc}", exc_info=True)


def send_wakeup() -> None:
    try:
        df4h = calculate_indicators(get_gold_4h())
        df1h = calculate_indicators(get_gold_1h())
        price = get_gold_price()
        _, htf_bias = get_htf_bias(df4h, df1h)
        bot.send_message(
            format_wakeup_message(price, df1h.iloc[-1], htf_bias=htf_bias),
            reply_markup=bot.get_main_keyboard(),
        )
        logger.info("Wakeup message sent.")
    except Exception as exc:
        logger.error(f"Wakeup error: {exc}", exc_info=True)


def send_sleep() -> None:
    try:
        price = get_gold_price()
        bot.send_message(format_sleep_message(price), reply_markup=bot.get_main_keyboard())
        logger.info("Sleep message sent.")
    except Exception as exc:
        logger.error(f"Sleep notice error: {exc}", exc_info=True)


def main() -> None:
    logger.info("Starting Gold Trading Bot …")

    if not bot.test_connection():
        logger.critical("Telegram connection failed — check token!")
        sys.exit(1)

    bot.send_message(format_startup(), reply_markup=bot.get_main_keyboard())
    logger.info("Startup message sent with main keyboard.")

    listener_thread = threading.Thread(
        target=start_listener,
        args=(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, scan_gold, daily_summary),
        daemon=True,
    )
    listener_thread.start()
    logger.info("Telegram interactive listener thread started.")

    scheduler = setup_scheduler(lambda: scan_gold(is_manual=False), send_wakeup, send_sleep)
    logger.info("Scheduler running (every 5 min, 10:00-00:00 Tehran). Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
