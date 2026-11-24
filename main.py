"""
Gold Trading Bot — Main Entry Point
Monitors XAU/USD across 4H / 1H / 30M timeframes.
Active hours: 12:00 – 00:00 Tehran time (scan every 15 min).
"""
import logging, sys

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

from data.gold   import get_gold_4h, get_gold_1h, get_gold_30m, get_gold_price
from data.news   import fetch_news

from strategies.indicators import calculate_indicators
from strategies.signals    import generate_signal

from bot.telegram_bot import TelegramBot
from bot.formatter    import format_signal, format_daily_summary, format_startup

from scheduler.runner import setup_scheduler

# ── Telegram ──────────────────────────────────────────────────────────────────
bot = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

# Dedup: remember last sent signal key
_last_key: str = ""


# ─── scan ─────────────────────────────────────────────────────────────────────

def scan_gold() -> None:
    global _last_key
    logger.info("=" * 55)
    logger.info("Gold scan started …")

    try:
        # Fetch multi-timeframe data
        df4h  = calculate_indicators(get_gold_4h())
        df1h  = calculate_indicators(get_gold_1h())
        df30m = calculate_indicators(get_gold_30m())

        price = get_gold_price()
        sig   = generate_signal(df4h, df1h, df30m, current_price=price["price"])

        if sig is None:
            logger.info("No signal generated.")
            return

        if sig.direction == "NONE":
            logger.info(f"Signal skipped: {sig.skip_reason}")
            return

        # Dedup: same direction + same confluence score = same signal
        key = f"{sig.direction}_{sig.confluence}_{round(sig.entry, 1)}"
        if key == _last_key:
            logger.info(f"Same signal as last scan ({key}), skipping.")
            return

        msg = format_signal(sig, price)
        if bot.send_message(msg):
            _last_key = key
            logger.info(
                f"Signal sent: {sig.direction}  entry={sig.entry}"
                f"  TP={sig.take_profit}  SL={sig.stop_loss}"
                f"  RR={sig.rr_ratio}  prob={sig.win_probability}%"
                f"  confluence={sig.confluence}/{sig.total_checks}"
            )

    except Exception as exc:
        logger.error(f"Scan error: {exc}", exc_info=True)
        bot.send_message(f"⚠️ خطا در اسکن طلا:\n`{str(exc)[:200]}`")


# ─── daily summary ─────────────────────────────────────────────────────────────

def daily_summary() -> None:
    try:
        price = get_gold_price()
        news  = fetch_news()
        # filter gold-related news
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

    bot.send_message(format_startup())
    logger.info("Startup message sent.")

    # First scan right away
    scan_gold()

    scheduler = setup_scheduler(scan_gold, daily_summary)
    logger.info("Scheduler running. Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
