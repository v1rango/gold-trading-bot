import os
from pathlib import Path
import pytz


def _load_dotenv(env_path: Path = Path(__file__).resolve().parent / ".env") -> None:
    """Load key=value pairs from a local .env file if present (without overriding existing env vars)."""
    if not env_path.is_file():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val:
                os.environ.setdefault(key, val)
    except OSError:
        pass


_load_dotenv()

# ===== Telegram (Environment Variables / .env / GitHub Secrets ONLY) =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_raw_chats = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = list(dict.fromkeys(
    [c.strip() for c in _raw_chats.split(",") if c.strip()]
))
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0] if TELEGRAM_CHAT_IDS else ""


def validate_telegram_config() -> tuple[str, list[str]]:
    """Ensure Telegram credentials are configured via environment variables."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN تنظیم نشده است! لطفاً آن را در متغیر محیطی (.env یا GitHub Secrets) تنظیم کنید."
        )
    if not TELEGRAM_CHAT_IDS:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID تنظیم نشده است! لطفاً حداقل یک Chat ID در متغیر محیطی (.env یا GitHub Secrets) تنظیم کنید."
        )
    return TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS

# ===== Gold =====
GOLD_SYMBOL = "OANDA:XAUUSD"

# ===== Timezone =====
TIMEZONE = pytz.timezone("Asia/Tehran")

# ===== Active hours (Tehran time) =====
START_HOUR = 10   # 10:00 AM
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
MIN_CONFLUENCE   = 6        # out of 8 indicators for 1H macro
MIN_RR_RATIO     = 2.0      # minimum Risk:Reward for 1H macro
ADX_TREND_MIN    = 20       # ADX below this = choppy market for 1H macro
ATR_SL_MULT      = 1.8      # stop loss = ATR * this multiplier (backtested optimal)
DEDUP_MINUTES    = 120      # min gap between same-direction signals across engines
STATE_FILE       = "state.json"

# ===== Scan interval =====
SCAN_MINUTES = 5            # scan every 5 minutes
