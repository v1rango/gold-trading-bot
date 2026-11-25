import os
import pytz

# ===== Telegram (Reads from Environment if available, else hardcoded) =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9005969882:AAHh3cR_s2xhmVT6cftymPxuKTs-sccQpaI")
_raw_chats = os.getenv("TELEGRAM_CHAT_ID", "8211920466")
_extra_chats = ["8211920466", "6641086503"]
TELEGRAM_CHAT_IDS = list(dict.fromkeys(
    [c.strip() for c in _raw_chats.split(",") if c.strip()] + _extra_chats
))
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0]

# ===== Gold =====
GOLD_SYMBOL = "OANDA:XAUUSD"

# ===== Timezone =====
TIMEZONE = pytz.timezone("Asia/Tehran")

# ===== Active hours (Tehran time) =====
START_HOUR = 12   # 12:00 PM
END_HOUR   = 24   # 12:00 AM

# ===== Indicator params =====
EMA_FAST   = 20
EMA_MID    = 50
EMA_SLOW   = 200

RSI_PERIOD     = 14
RSI_OVERSOLD   = 35
RSI_OVERBOUGHT = 65

MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_STD    = 2.0

ATR_PERIOD = 14
ADX_PERIOD = 14

STOCH_PERIOD = 14
STOCH_SMOOTH = 3

# ===== Signal quality filters =====
MIN_CONFLUENCE   = 6        # out of 8 indicators (must align with 4H trend + ADX)
MIN_RR_RATIO     = 2.0      # minimum Risk:Reward to send signal
ADX_TREND_MIN    = 20       # ADX below this = choppy market, skip
ATR_SL_MULT      = 1.8      # stop loss = ATR * this multiplier (backtested optimal)

# ===== Scan interval =====
SCAN_MINUTES = 10           # scan every 10 minutes
