"""
Gold Trading Bot — Main Entry Point
Monitors XAU/USD (OANDA Spot) across 4H / 1H / 30M timeframes.
Active hours: 12:00 – 00:00 Tehran time (scan every 10 min).
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

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from data.gold import get_gold_4h, get_gold_1h, get_gold_30m, get_gold_price
from data.news import fetch_news
from strategies.indicators import calculate_indicators
from strategies.signals import generate_signal
from bot.telegram_bot import TelegramBot
from bot.formatter import format_signal, format_daily_summary, format_startup, format_manual_status
from bot.listener import start_listener
from scheduler.runner import setup_scheduler

# ── Telegram ──────────────────────────────────────────────────────────────────
bot = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

# Dedup: remember last sent signal key
_last_key: str = ""


# ─── scan ─────────────────────────────────────────────────────────────────────

def scan_gold(is_manual: bool = False) -> None:
    global _last_key
    logger.info("=" * 55)
    logger.info(f"Gold scan started (manual={is_manual}) …")

    try:
        # Fetch multi-timeframe data
        df4h  = calculate_indicators(get_gold_4h())
        df1h  = calculate_indicators(get_gold_1h())
        df30m = calculate_indicators(get_gold_30m())

        price = get_gold_price()
        sig   = generate_signal(df4h, df1h, df30m, current_price=price["price"])

        # 1. Valid Signal Found -> Send full signal alert
        if sig is not None and sig.direction in ("BUY", "SELL"):
            key = f"{sig.direction}_{sig.confluence}_{round(sig.entry, 1)}"
            if key != _last_key or is_manual:
                msg = format_signal(sig, price)
                if bot.send_message(msg, reply_markup=bot.get_scan_inline_keyboard()):
                    _last_key = key
                    logger.info(
                        f"Signal sent: {sig.direction} entry={sig.entry} "
                        f"TP={sig.take_profit} SL={sig.stop_loss} "
                        f"RR={sig.rr_ratio} prob={sig.win_probability}%"
                    )
            else:
                logger.info(f"Same signal as before ({key}), skipped.")
            return

        # 2. Manual Scan Request -> Provide informative market status report
        if is_manual:
            status_msg = format_manual_status(price, df1h.iloc[-1], sig.skip_reason)
            bot.send_message(status_msg, reply_markup=bot.get_scan_inline_keyboard())
            logger.info("Manual scan status sent to Telegram.")
        else:
            logger.info(f"Automatic scan completed silently: {sig.skip_reason}")

    except Exception as exc:
        logger.error(f"Scan error: {exc}", exc_info=True)
        if is_manual:
            bot.send_message(f"⚠️ خطا در اسکن طلا:\n`{str(exc)[:200]}`")


# ─── daily summary ─────────────────────────────────────────────────────────────

def daily_summary() -> None:
    try:
        price = get_gold_price()
        news  = fetch_news()
        gold_news = [n for n in news if n["type"] == "GOLD"] or news[:3]
        bot.send_message(format_daily_summary(price, gold_news))
        logger.info("Daily summary sent.")
    except Exception as exc:
        logger.error(f"Daily summary error: {exc}", exc_info=True)


# ─── entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Starting Gold Trading Bot …")

    if not bot.test_connection():
        logger.critical("Telegram connection failed — check token!")
        sys.exit(1)

    # 1. Send startup welcome message with bottom buttons
    bot.send_message(format_startup(), reply_markup=bot.get_main_keyboard())
    logger.info("Startup message sent with main keyboard.")

    # 2. Start real-time Telegram button listener in a background thread
    listener_thread = threading.Thread(
        target=start_listener,
        args=(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, scan_gold, daily_summary),
        daemon=True,
    )
    listener_thread.start()
    logger.info("Telegram interactive listener thread started.")

    # 3. Setup and start scheduled scans (every 10 minutes)
    scheduler = setup_scheduler(lambda: scan_gold(is_manual=False), daily_summary)
    logger.info("Scheduler running (every 10 min). Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
