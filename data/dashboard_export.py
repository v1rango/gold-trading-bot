"""
Exports real-time market snapshot, bot signal history, auto TP/SL checks,
and weekly USD economic calendar to `dashboard/data/dashboard_data.json`
for the GitHub Pages trading dashboard.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from config import TIMEZONE

logger = logging.getLogger("dashboard_export")

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
HISTORY_FILE = "dashboard_history.json"
OUTPUT_JSON_PATH = Path("dashboard") / "data" / "dashboard_data.json"
MAX_SIGNALS_KEEP = 80


def _safe_float(val: Any, digits: int = 2) -> Optional[float]:
    try:
        if val is None or pd.isna(val):
            return None
        return round(float(val), digits)
    except Exception:
        return None


def _load_history() -> Dict[str, Any]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("signals", [])
                data.setdefault("news", [])
                data.setdefault("news_updated_utc", "")
                data.setdefault("market", {})
                return data
        except Exception as e:
            logger.warning(f"Failed to read {HISTORY_FILE}: {e}")
    return {"signals": [], "news": [], "news_updated_utc": "", "market": {}}


def _atomic_json_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".dash_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _save_history(history: Dict[str, Any]) -> None:
    try:
        _atomic_json_write(Path(HISTORY_FILE), history)
    except Exception as e:
        logger.warning(f"Failed to write {HISTORY_FILE}: {e}")


def _fetch_economic_news(existing_news: Optional[List[dict]] = None) -> List[dict]:
    """Fetch weekly USD High/Medium impact calendar from ForexFactory JSON."""
    now_tehran = datetime.now(TIMEZONE)
    today_tehran = now_tehran.strftime("%Y-%m-%d")

    try:
        r = requests.get(
            FF_CALENDAR_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        raw_events = r.json()
        if not isinstance(raw_events, list):
            raise ValueError("Unexpected calendar payload")

        parsed: List[dict] = []
        for ev in raw_events:
            country = str(ev.get("country", "")).upper()
            impact = str(ev.get("impact", "")).strip()
            if country != "USD" or impact not in ("High", "Medium"):
                continue

            date_raw = ev.get("date", "")
            dt_tehran = None
            tehran_time = "--:--"
            tehran_date = ""
            iso_utc = ""
            is_past = False
            is_today = False

            if date_raw:
                try:
                    dt = datetime.fromisoformat(str(date_raw))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_tehran = dt.astimezone(TIMEZONE)
                    tehran_time = dt_tehran.strftime("%H:%M")
                    tehran_date = dt_tehran.strftime("%Y-%m-%d")
                    iso_utc = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    is_today = tehran_date == today_tehran
                    is_past = dt_tehran < now_tehran
                except Exception:
                    pass

            parsed.append({
                "title": str(ev.get("title", "")).strip(),
                "country": country,
                "impact": impact,
                "date_utc": iso_utc,
                "tehran_date": tehran_date,
                "tehran_time": tehran_time,
                "is_today": is_today,
                "is_past": is_past,
                "forecast": str(ev.get("forecast") or "").strip(),
                "previous": str(ev.get("previous") or "").strip(),
                "actual": str(ev.get("actual") or "").strip(),
            })

        parsed.sort(key=lambda x: x.get("date_utc") or "")
        return parsed
    except Exception as e:
        logger.warning(f"Economic calendar fetch failed (using cached): {e}")
        # Refresh dynamic is_today / is_past flags on cached events
        fallback = existing_news or []
        for item in fallback:
            if item.get("date_utc"):
                try:
                    dt = datetime.fromisoformat(item["date_utc"].replace("Z", "+00:00"))
                    dt_tehran = dt.astimezone(TIMEZONE)
                    item["is_today"] = dt_tehran.strftime("%Y-%m-%d") == today_tehran
                    item["is_past"] = dt_tehran < now_tehran
                except Exception:
                    pass
        return fallback


def _extract_tf_snapshot(df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    if df is None or df.empty:
        return {}
    row = df.iloc[-1]
    return {
        "close": _safe_float(row.get("close")),
        "rsi": _safe_float(row.get("rsi"), 1),
        "rsi_7": _safe_float(row.get("rsi_7"), 1),
        "ema_20": _safe_float(row.get("ema_20")),
        "ema_50": _safe_float(row.get("ema_50")),
        "ema_200": _safe_float(row.get("ema_200")),
        "atr": _safe_float(row.get("atr")),
        "adx": _safe_float(row.get("adx"), 1),
        "osc_k": _safe_float(row.get("osc_k"), 1),
        "osc_d": _safe_float(row.get("osc_d"), 1),
        "bb_upper": _safe_float(row.get("bb_upper")),
        "bb_lower": _safe_float(row.get("bb_lower")),
        "macd_hist": _safe_float(row.get("macd_hist"), 3),
    }


def _to_naive_utc(ts: Any) -> Optional[pd.Timestamp]:
    try:
        t = pd.Timestamp(ts)
        if t.tzinfo is not None:
            t = t.tz_convert("UTC").tz_localize(None)
        return t
    except Exception:
        return None


def _evaluate_open_signals(signals: List[dict], df5m: Optional[pd.DataFrame]) -> List[dict]:
    """
    Check 5m OHLC candles since each signal to detect TP_HIT, SL_HIT, or 1R breakeven.
    Returns newly triggered lifecycle events for open signals only.
    """
    events: List[dict] = []
    if df5m is None or df5m.empty or not signals:
        return events

    df_eval = df5m.copy()
    idx_utc = [_to_naive_utc(i) for i in df_eval.index]
    df_eval["_utc"] = idx_utc
    df_eval = df_eval.sort_values("_utc")

    for sig in signals:
        if sig.get("auto_outcome") in ("TP_HIT", "SL_HIT"):
            continue
        sig_utc = _to_naive_utc(sig.get("timestamp_utc"))
        if sig_utc is None:
            continue

        # Only examine 5m candles whose bar open time is at or after signal emission
        sub = df_eval[df_eval["_utc"] >= sig_utc]
        if sub.empty:
            continue

        entry = float(sig.get("entry", 0.0))
        tp = float(sig["take_profit"])
        sl = float(sig["stop_loss"])
        direction = sig.get("direction")
        risk_dist = abs(entry - sl)
        be_1r = (entry + risk_dist) if direction == "BUY" else (entry - risk_dist)

        outcome = "OPEN"
        hit_1r = False
        for _, bar in sub.iterrows():
            hi = float(bar["high"])
            lo = float(bar["low"])
            if direction == "BUY":
                if lo <= sl:
                    outcome = "SL_HIT"
                    break
                if hi >= tp:
                    outcome = "TP_HIT"
                    break
                if risk_dist > 0 and hi >= be_1r:
                    hit_1r = True
            elif direction == "SELL":
                if hi >= sl:
                    outcome = "SL_HIT"
                    break
                if lo <= tp:
                    outcome = "TP_HIT"
                    break
                if risk_dist > 0 and lo <= be_1r:
                    hit_1r = True

        sig["auto_outcome"] = outcome
        if outcome in ("TP_HIT", "SL_HIT"):
            events.append({"type": outcome, "signal": dict(sig)})
        elif hit_1r and not sig.get("alerted_1r"):
            sig["alerted_1r"] = True
            events.append({"type": "BREAKEVEN_1R", "signal": dict(sig)})

    return events


def get_economic_calendar() -> List[dict]:
    """Fetch current weekly USD High/Medium calendar with cached fallback."""
    history = _load_history()
    return _fetch_economic_news(history.get("news"))


def _make_signal_id(sig: Any, ts_utc_iso: str) -> str:
    raw = f"{ts_utc_iso[:16]}|{sig.strategy_name}|{sig.direction}|{sig.entry}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _write_output_json(payload: Dict[str, Any]) -> None:
    _atomic_json_write(OUTPUT_JSON_PATH, payload)


def export_dashboard_snapshot(
    price: dict,
    df4h: Optional[pd.DataFrame] = None,
    df1h: Optional[pd.DataFrame] = None,
    df30m: Optional[pd.DataFrame] = None,
    df15m: Optional[pd.DataFrame] = None,
    df5m: Optional[pd.DataFrame] = None,
    htf_bias: str = "NEUTRAL",
    htf_text: str = "",
    reason_1h: str = "",
    emitted_signals: Optional[List[Any]] = None,
    risk_info: Optional[Dict[str, Any]] = None,
    news_items: Optional[List[dict]] = None,
) -> List[dict]:
    """Update persistent dashboard history and write static JSON for GitHub Pages."""
    history = _load_history()
    now_utc = datetime.now(timezone.utc)
    now_tehran = datetime.now(TIMEZONE)

    ts_utc_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_tehran_str = now_tehran.strftime("%Y-%m-%d %H:%M")

    signals: List[dict] = history.get("signals", [])
    existing_ids = {s.get("id") for s in signals}

    for sig in (emitted_signals or []):
        sig_id = _make_signal_id(sig, ts_utc_iso)
        if sig_id in existing_ids:
            continue
        passed_reasons = [
            f"{c.name}: {c.detail}" for c in getattr(sig, "checks", []) if c.passed
        ][:4]
        entry = {
            "id": sig_id,
            "timestamp_utc": ts_utc_iso,
            "timestamp_tehran": ts_tehran_str,
            "strategy_name": sig.strategy_name,
            "timeframe": sig.timeframe,
            "direction": sig.direction,
            "entry": round(float(sig.entry), 2),
            "stop_loss": round(float(sig.stop_loss), 2),
            "take_profit": round(float(sig.take_profit), 2),
            "rr_ratio": round(float(sig.rr_ratio), 2),
            "win_probability": round(float(sig.win_probability), 1),
            "confluence": int(getattr(sig, "confluence", 0)),
            "total_checks": int(getattr(sig, "total_checks", 0)),
            "reasons": passed_reasons,
            "auto_outcome": "OPEN",
        }
        signals.insert(0, entry)
        existing_ids.add(sig_id)

    lifecycle_events = _evaluate_open_signals(signals, df5m)
    signals = signals[:MAX_SIGNALS_KEEP]

    news = news_items if news_items is not None else _fetch_economic_news(history.get("news"))
    risk = risk_info or {}

    market_snapshot = {
        "price": price.get("price"),
        "bid": price.get("bid"),
        "ask": price.get("ask"),
        "spread": risk.get("spread"),
        "spread_warning": risk.get("spread_warning", ""),
        "news_warning": risk.get("news_warning", ""),
        "change_24h": price.get("change_24h", 0.0),
        "source": price.get("source", "OANDA:XAUUSD"),
        "htf_bias": htf_bias,
        "htf_text": htf_text,
        "reason_1h": reason_1h,
        "indicators_4h": _extract_tf_snapshot(df4h),
        "indicators_1h": _extract_tf_snapshot(df1h),
        "indicators_30m": _extract_tf_snapshot(df30m),
        "indicators_15m": _extract_tf_snapshot(df15m),
        "indicators_5m": _extract_tf_snapshot(df5m),
    }

    payload = {
        "updated_at_utc": ts_utc_iso,
        "updated_at_tehran": ts_tehran_str,
        "market": market_snapshot,
        "signals": signals,
        "news": news,
    }

    history["signals"] = signals
    history["news"] = news
    history["news_updated_utc"] = ts_utc_iso
    history["updated_at_tehran"] = ts_tehran_str
    history["market"] = market_snapshot
    _save_history(history)
    _write_output_json(payload)
    logger.info(f"Dashboard snapshot exported ({len(signals)} signals, {len(news)} news items).")
    return lifecycle_events


def _news_signature(items: Optional[List[dict]]) -> List[tuple]:
    return [
        (
            item.get("title", ""),
            item.get("date_utc", ""),
            item.get("actual", ""),
            bool(item.get("is_today", False)),
        )
        for item in (items or [])
    ]


def refresh_dashboard_from_cache(price: Optional[dict] = None) -> bool:
    """
    Lightweight refresh when outside active scan hours (e.g. weekends/night).
    Returns True if meaningful data (price, news items, or initial file) changed.
    """
    history = _load_history()
    now_utc = datetime.now(timezone.utc)
    now_tehran = datetime.now(TIMEZONE)
    ts_utc_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_tehran_str = now_tehran.strftime("%Y-%m-%d %H:%M")

    prev_news = history.get("news", [])
    news = _fetch_economic_news(prev_news)
    market = history.get("market", {})
    has_price_update = bool(price and price.get("price"))
    if has_price_update:
        market = {**market, **price}

    meaningful_change = (
        has_price_update
        or not OUTPUT_JSON_PATH.exists()
        or _news_signature(news) != _news_signature(prev_news)
    )

    payload = {
        "updated_at_utc": ts_utc_iso,
        "updated_at_tehran": ts_tehran_str,
        "market": market,
        "signals": history.get("signals", []),
        "news": news,
    }
    history["news"] = news
    history["news_updated_utc"] = ts_utc_iso
    history["updated_at_tehran"] = ts_tehran_str
    history["market"] = market
    _save_history(history)
    _write_output_json(payload)
    return meaningful_change
