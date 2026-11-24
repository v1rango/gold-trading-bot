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

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from data.gold import get_gold_4h, get_gold_1h, get_gold_30m, get_gold_price
from strategies.indicators import calculate_indicators
from strategies.signals import generate_signal
from bot.telegram_bot import TelegramBot
from bot.formatter import format_signal, _now


def main():
    parser = argparse.ArgumentParser(description="Gold Market Scanner")
    parser.add_argument("--manual", action="store_true", help="Manual scan (always reports status)")
    args = parser.parse_args()

    bot = TelegramBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    logger.info("Starting single scan...")
    try:
        df4h  = calculate_indicators(get_gold_4h())
        df1h  = calculate_indicators(get_gold_1h())
        df30m = calculate_indicators(get_gold_30m())
        price = get_gold_price()

        sig = generate_signal(df4h, df1h, df30m, current_price=price["price"])

        # 1. If valid signal found -> send full signal
        if sig is not None and sig.direction in ("BUY", "SELL"):
            logger.info(f"Signal found: {sig.direction} at {sig.entry}")
            msg = format_signal(sig, price)
            bot.send_message(msg)
            return

        # 2. If manual scan requested -> notify user of market status
        if args.manual:
            reason = sig.skip_reason if sig else "عدم تطابق شروط ورود"
            curr_1h = df1h.iloc[-1]
            status_msg = (
                f"🔍 *گزارش اسکن دستی طلا*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 قیمت لحظه‌ای: `${price['price']:,.2f}`\n"
                f"📊 وضعیت بازار: `{reason}`\n"
                f"📈 شاخص روند (ADX): `{curr_1h['adx']:.1f}`\n"
                f"⚡ شاخص مومنتوم (RSI): `{curr_1h['rsi']:.1f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"ℹ️ _سیگنال ورود با شرایط معتبر یافت نشد._\n"
                f"🕐 `{_now()}`"
            )
            bot.send_message(status_msg)
            logger.info("Manual scan status sent to Telegram.")
        else:
            logger.info(f"Scan finished silently: {sig.skip_reason if sig else 'No signal'}")

    except Exception as e:
        logger.error(f"Error during scan: {e}", exc_info=True)
        if args.manual:
            bot.send_message(f"⚠️ خطا در اسکن طلا:\n`{str(e)[:200]}`")
        sys.exit(1)


if __name__ == "__main__":
    main()
