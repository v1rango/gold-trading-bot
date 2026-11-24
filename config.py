import os
import pytz

# ===== Telegram (Reads from Environment if available, else hardcoded) =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9005969882:AAHh3cR_s2xhmVT6cftymPxuKTs-sccQpaI")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "8211920466")

# ===== Gold =====
GOLD_SYMBOL = "GC=F"

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
MIN_CONFLUENCE   = 5        # out of 8 indicators
MIN_RR_RATIO     = 2.0      # minimum Risk:Reward to send signal
ADX_TREND_MIN    = 20       # ADX below this = choppy market, skip
ATR_SL_MULT      = 1.5      # stop loss = ATR * this multiplier

# ===== Scan interval =====
SCAN_MINUTES = 10           # scan every 10 minutes
