import requests
import pandas as pd
import time
import logging

logger = logging.getLogger(__name__)
KUCOIN_BASE = "https://api.kucoin.com/api/v1"


def get_kucoin_candles(symbol: str, timeframe: str, limit: int = 150) -> pd.DataFrame:
    """
    Fetch OHLCV candles from KuCoin public API (no auth required).
    timeframe: '15min' | '30min' | '1hour'
    Returns DataFrame sorted oldest -> newest.
    """
    tf_seconds = {"15min": 900, "30min": 1800, "1hour": 3600}
    seconds = tf_seconds.get(timeframe, 3600)

    end_time   = int(time.time())
    start_time = end_time - (limit * seconds)

    params = {
        "type":    timeframe,
        "symbol":  symbol,
        "startAt": start_time,
        "endAt":   end_time,
    }

    resp = requests.get(f"{KUCOIN_BASE}/market/candles", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "200000" or not data.get("data"):
        raise ValueError(f"KuCoin candles error: {data}")

    # KuCoin returns newest first → reverse
    candles = list(reversed(data["data"]))

    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "close", "high", "low", "volume", "turnover"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="s")
    df = df.astype({"open": float, "close": float, "high": float, "low": float, "volume": float})
    df.set_index("timestamp", inplace=True)
    return df


def get_btc_price() -> dict:
    """Get current BTC/USDT live stats from KuCoin."""
    resp = requests.get(
        f"{KUCOIN_BASE}/market/stats",
        params={"symbol": "BTC-USDT"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "200000":
        raise ValueError(f"KuCoin stats error: {data}")

    s = data["data"]
    return {
        "price":      float(s["last"]),
        "change_24h": float(s["changeRate"]) * 100,
        "high_24h":   float(s["high"]),
        "low_24h":    float(s["low"]),
        "volume_24h": float(s["vol"]),
    }
