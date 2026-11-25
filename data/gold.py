"""
Real-time Gold (XAU/USD) data fetcher.
Primary:  TradingView WebSocket (OANDA:XAUUSD, fallback TVC:GOLD / FOREXCOM:XAUUSD)
          -> Zero delay, exact Forex Spot XAU/USD price & gapless OHLCV candles.
Fallback: Swissquote live BBO feed, TradingView Scanner API, InstaForex, yfinance (GC=F).
"""
import json
import logging
import math
import random
import re
import string
import time
from typing import Dict, Optional, Tuple

import pandas as pd
import requests
import websocket
import yfinance as yf

logger = logging.getLogger(__name__)

TV_WS_URL = "wss://data.tradingview.com/socket.io/websocket"
TV_ORIGIN = "https://www.tradingview.com"
TV_SYMBOLS = ("OANDA:XAUUSD", "TVC:GOLD", "FOREXCOM:XAUUSD")
TV_INTERVAL_MAP = {"5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240"}

SWISSQUOTE_URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD"
TV_SCANNER_URL = "https://scanner.tradingview.com/cfd/scan"
INSTAFOREX_URL = "https://quotes.instaforex.com/api/quotesTick?m=json&q=xauusd"


def _tv_send(ws, func: str, args: list) -> None:
    msg = json.dumps({"m": func, "p": args}, separators=(",", ":"))
    ws.send(f"~m~{len(msg)}~m~{msg}")


def _tv_parse_frames(raw: str) -> list:
    frames = []
    for part in re.split(r"~m~\d+~m~", raw):
        if not part:
            continue
        try:
            frames.append(json.loads(part))
        except Exception:
            pass
    return frames


def _rand_id(prefix: str) -> str:
    return prefix + "_" + "".join(random.choices(string.ascii_lowercase, k=12))


def _fetch_tv_candles(interval: str, bars: int = 350) -> pd.DataFrame:
    """Fetch exact Spot XAU/USD OHLCV candles from TradingView WebSocket."""
    tv_tf = TV_INTERVAL_MAP.get(interval, "60")
    last_err = None

    for symbol in TV_SYMBOLS:
        ws = None
        try:
            ws = websocket.create_connection(TV_WS_URL, origin=TV_ORIGIN, timeout=10)
            cs = _rand_id("cs")
            _tv_send(ws, "set_auth_token", ["unauthorized_user_token"])
            _tv_send(ws, "chart_create_session", [cs, ""])
            _tv_send(ws, "resolve_symbol", [cs, "sds_sym_1", "=" + json.dumps({"symbol": symbol, "adjustment": "splits"})])
            _tv_send(ws, "create_series", [cs, "sds_1", "s1", "sds_sym_1", tv_tf, bars, ""])

            candles = []
            for _ in range(35):
                raw = ws.recv()
                if "~h~" in raw:
                    ws.send(raw)
                    continue
                for obj in _tv_parse_frames(raw):
                    m = obj.get("m")
                    if m == "timescale_update":
                        items = obj["p"][1].get("sds_1", {}).get("s", [])
                        for item in items:
                            v = item["v"]
                            candles.append({
                                "timestamp": pd.to_datetime(int(v[0]), unit="s"),
                                "open": float(v[1]),
                                "high": float(v[2]),
                                "low": float(v[3]),
                                "close": float(v[4]),
                                "volume": float(v[5]) if len(v) > 5 else 0.0,
                            })
                    elif m == "series_completed":
                        break
                    elif m in ("series_error", "symbol_error"):
                        raise ValueError(f"TradingView error for {symbol}: {obj}")
                else:
                    continue
                break

            if len(candles) >= 50:
                df = pd.DataFrame(candles).set_index("timestamp").sort_index()
                df.dropna(inplace=True)
                logger.info(f"Fetched {len(df)} candles ({interval}) from {symbol}")
                return df
        except Exception as e:
            last_err = e
            logger.warning(f"TradingView candles failed for {symbol} ({interval}): {e}")
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    raise RuntimeError(f"TradingView candle fetch failed: {last_err}")


def _fetch_yf_candles(interval: str, period: str) -> pd.DataFrame:
    """Emergency fallback using Yahoo Finance GC=F."""
    gold = yf.Ticker("GC=F")
    df = gold.history(period=period, interval=interval)
    if df is None or df.empty:
        raise ValueError(f"Yahoo Finance returned empty data for {interval}/{period}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]].copy()
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.dropna(inplace=True)
    return df


def _get_tf_candles(tv_tf: str, yf_interval: str, yf_period: str, limit: int) -> pd.DataFrame:
    """Fetch candles for any timeframe with TradingView primary and yfinance fallback."""
    try:
        return _fetch_tv_candles(tv_tf, limit).tail(limit)
    except Exception as e:
        logger.warning(f"Falling back to yfinance for {tv_tf}: {e}")
        return _fetch_yf_candles(yf_interval, yf_period).tail(limit)


def get_gold_4h(limit: int = 350) -> pd.DataFrame:
    """4-hour XAU/USD candles (350 bars for accurate EMA200)."""
    try:
        return _fetch_tv_candles("4h", limit).tail(limit)
    except Exception as e:
        logger.warning(f"Falling back to yfinance for 4H: {e}")
        df = _fetch_yf_candles("1h", "3mo")
        df_4h = df.resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        return df_4h.tail(limit)


def get_gold_1h(limit: int = 350) -> pd.DataFrame:
    """1-hour XAU/USD candles (350 bars for accurate EMA200)."""
    return _get_tf_candles("1h", "1h", "3mo", limit)


def get_gold_30m(limit: int = 300) -> pd.DataFrame:
    """30-minute XAU/USD candles."""
    return _get_tf_candles("30m", "30m", "30d", limit)


def get_gold_15m(limit: int = 300) -> pd.DataFrame:
    """15-minute XAU/USD candles."""
    return _get_tf_candles("15m", "15m", "15d", limit)


def get_gold_5m(limit: int = 300) -> pd.DataFrame:
    """5-minute XAU/USD candles."""
    return _get_tf_candles("5m", "5m", "5d", limit)


def _get_tv_ws_quote() -> Optional[Dict]:
    """Fetch real-time sub-second XAU/USD quote from TradingView WebSocket."""
    ws = None
    try:
        ws = websocket.create_connection(TV_WS_URL, origin=TV_ORIGIN, timeout=8)
        qs = _rand_id("qs")
        _tv_send(ws, "set_auth_token", ["unauthorized_user_token"])
        _tv_send(ws, "quote_create_session", [qs])
        _tv_send(ws, "quote_add_symbols", [qs, "OANDA:XAUUSD", "TVC:GOLD"])

        quotes: Dict[str, dict] = {}
        for _ in range(20):
            raw = ws.recv()
            if "~h~" in raw:
                ws.send(raw)
                continue
            for obj in _tv_parse_frames(raw):
                if obj.get("m") == "qsd":
                    sym = obj["p"][1].get("n")
                    vals = obj["p"][1].get("v", {})
                    if sym:
                        quotes.setdefault(sym, {}).update(vals)
            if "lp" in quotes.get("OANDA:XAUUSD", {}) and "chp" in quotes.get("OANDA:XAUUSD", {}):
                break

        q = quotes.get("OANDA:XAUUSD") or quotes.get("TVC:GOLD")
        if q and q.get("lp"):
            price = float(q["lp"])
            chp = float(q.get("chp", 0.0))
            return {
                "price": round(price, 2),
                "change_24h": round(chp, 2),
                "bid": round(float(q.get("bid", price)), 2),
                "ask": round(float(q.get("ask", price)), 2),
                "source": q.get("original_name", "OANDA:XAUUSD"),
            }
    except Exception as e:
        logger.warning(f"TV WS quote failed: {e}")
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    return None


def _get_swissquote_quote() -> Optional[Dict]:
    """Fallback: Swissquote real-time XAU/USD institutional forex feed."""
    try:
        r = requests.get(SWISSQUOTE_URL, timeout=5)
        r.raise_for_status()
        data = r.json()
        # Use tightest spread profile (elite/prime/standard)
        profiles = data[0]["spreadProfilePrices"]
        best_p = min(profiles, key=lambda x: x["ask"] - x["bid"])
        mid = (float(best_p["bid"]) + float(best_p["ask"])) / 2.0
        return {
            "price": round(mid, 2),
            "change_24h": 0.0,
            "bid": round(float(best_p["bid"]), 2),
            "ask": round(float(best_p["ask"]), 2),
            "source": "Swissquote XAU/USD",
        }
    except Exception as e:
        logger.warning(f"Swissquote quote failed: {e}")
    return None


def _get_tv_scanner_quote() -> Optional[Dict]:
    """Fallback: TradingView HTTP Scanner quote for OANDA:XAUUSD."""
    try:
        r = requests.post(
            TV_SCANNER_URL,
            json={"symbols": {"tickers": ["OANDA:XAUUSD", "TVC:GOLD"]}, "columns": ["close", "change"]},
            timeout=5,
        )
        r.raise_for_status()
        rows = r.json().get("data", [])
        if rows:
            d = rows[0]["d"]
            return {
                "price": round(float(d[0]), 2),
                "change_24h": round(float(d[1] or 0.0), 2),
                "source": rows[0]["s"],
            }
    except Exception as e:
        logger.warning(f"TV Scanner quote failed: {e}")
    return None


def get_gold_price() -> dict:
    """
    Get exact real-time Spot Gold (XAU/USD) price.
    Avoids delayed futures (GC=F) unless every real-time spot source fails.
    """
    # 1. TradingView real-time WebSocket (OANDA:XAUUSD)
    res = _get_tv_ws_quote()
    if res and res["price"] > 0:
        return res

    # 2. TradingView HTTP Scanner (includes 24h change)
    res_tv = _get_tv_scanner_quote()
    res_sq = _get_swissquote_quote()

    if res_sq and res_sq["price"] > 0:
        if res_tv:
            res_sq["change_24h"] = res_tv["change_24h"]
        return res_sq

    if res_tv and res_tv["price"] > 0:
        return res_tv

    # 3. InstaForex tick feed
    try:
        r = requests.get(INSTAFOREX_URL, timeout=5)
        r.raise_for_status()
        item = r.json()[0]
        mid = (float(item["bid"]) + float(item["ask"])) / 2.0
        return {
            "price": round(mid, 2),
            "change_24h": round(float(item.get("change", 0.0)), 2),
            "source": "InstaForex XAUUSD",
        }
    except Exception as e:
        logger.warning(f"InstaForex quote failed: {e}")

    # 4. Last resort: yfinance GC=F
    gold = yf.Ticker("GC=F")
    last = None
    try:
        raw_val = gold.fast_info.last_price
        if raw_val is not None and not math.isnan(raw_val) and raw_val > 0:
            last = float(raw_val)
    except Exception:
        pass
    if last is None:
        df1h = _fetch_yf_candles("1h", "5d")
        last = float(df1h["close"].iloc[-1])

    return {"price": round(last, 2), "change_24h": 0.0, "source": "Yahoo GC=F (fallback)"}
