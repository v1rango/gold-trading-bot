"""
Gold (GC=F) data fetcher via yfinance.
Provides 4H (resampled from 1H), 1H, and 30M candles.
"""
import yfinance as yf
import pandas as pd
import logging
import math
import time

logger = logging.getLogger(__name__)


def _fetch_raw(interval: str, period: str, max_retries: int = 2) -> pd.DataFrame:
    # Standard periods accepted by Yahoo Finance
    fallback_periods = [period, "3mo", "60d"] if interval == "1h" else [period, "30d", "60d"]
    df = None

    for p in fallback_periods:
        for attempt in range(max_retries):
            try:
                gold = yf.Ticker("GC=F")
                df = gold.history(period=p, interval=interval)
                if df is not None and not df.empty and len(df) >= 20:
                    break
            except Exception as e:
                logger.warning(f"Fetch failed for {p} attempt {attempt+1}: {e}")
            time.sleep(0.5)
        if df is not None and not df.empty and len(df) >= 20:
            break

    if df is None or df.empty:
        raise ValueError(f"داده‌ای برای طلا با تایم‌فریم {interval} دریافت نشد.")

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={"Open": "open", "High": "high",
                             "Low": "low",  "Close": "close",
                             "Volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]].copy()

    # Safely strip timezone without throwing AttributeError
    if hasattr(df.index, "tz") and df.index.tz is not None:
        try:
            df.index = df.index.tz_localize(None)
        except Exception:
            try:
                df.index = df.index.tz_convert(None)
            except Exception:
                pass

    df.dropna(inplace=True)
    return df


def get_gold_4h(limit: int = 350) -> pd.DataFrame:
    """4-hour candles (resampled from 1H, with enough history for EMA200)."""
    df = _fetch_raw("1h", "3mo")
    df_4h = df.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()
    return df_4h.tail(limit)


def get_gold_1h(limit: int = 350) -> pd.DataFrame:
    """1-hour candles (with enough history for EMA200)."""
    df = _fetch_raw("1h", "3mo")
    return df.tail(limit)


def get_gold_30m(limit: int = 250) -> pd.DataFrame:
    """30-minute candles."""
    df = _fetch_raw("30m", "30d")
    return df.tail(limit)


def get_gold_price() -> dict:
    """
    Live Gold price — uses fast_info/1m for real-time accuracy,
    with safe NaN and error fallbacks.
    """
    gold = yf.Ticker("GC=F")
    last = None

    # 1. Real-time fast_info
    try:
        raw_val = gold.fast_info.last_price
        if raw_val is not None and not math.isnan(raw_val) and raw_val > 0:
            last = float(raw_val)
    except Exception:
        last = None

    # 2. Fallback: 1-minute close
    if last is None:
        try:
            df1m = gold.history(period="1d", interval="1m")
            if df1m is not None and not df1m.empty:
                val = float(df1m["Close"].iloc[-1])
                if not math.isnan(val) and val > 0:
                    last = val
        except Exception:
            pass

    # 3. 24h change & fallback price from 1h data
    try:
        df1h = _fetch_raw("1h", "5d")
    except Exception:
        df1h = pd.DataFrame()

    if last is None and not df1h.empty:
        last = float(df1h["close"].iloc[-1])

    if not df1h.empty and len(df1h) >= 24 and last is not None:
        prev_24h = float(df1h["close"].iloc[-24])
        change   = ((last - prev_24h) / prev_24h) * 100
    elif not df1h.empty and len(df1h) >= 2 and last is not None:
        prev = float(df1h["close"].iloc[-2])
        change = ((last - prev) / prev) * 100
    else:
        change = 0.0

    return {"price": round(last, 2) if last else 0.0, "change_24h": round(change, 2)}
