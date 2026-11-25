"""
Multi-Timeframe Gold Signal Engine (4H + 1H + 30M + 15M + 5M).
Combines 4 backtest-proven trend-aligned engines with persistent deduplication:
  1. 1H_Macro      — 8-check MTF confluence (R:R >= 2.0)
  2. 30M_Precision — 4H+1H trend + StochRSI / RSI7 pullback (SL=1.5*ATR, R:R=1.5)
  3. 15M_Sniper    — 4H+1H trend + BB/Stoch/RSI7/3-Candle setup (SL=1.5-1.8*ATR, R:R=1.5-2.0)
  4. 5M_Sniper     — 4H+1H trend + BB/Stoch/StochRSI pullback + drift guard (SL=1.8*ATR, R:R=1.8)
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import DEDUP_MINUTES, STATE_FILE
from strategies.signals import Check, TradingSignal, generate_signal

logger = logging.getLogger(__name__)


# ── State Persistence (prevents duplicate signals across 5-min cloud runs) ───

def load_state(path: str = STATE_FILE) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("last_dir_utc", {})
                data.setdefault("last_engine_bar", {})
                return data
        except Exception as e:
            logger.warning(f"Could not read state file {path}: {e}")
    return {"last_dir_utc": {}, "last_engine_bar": {}}


def save_state(state: dict, path: str = STATE_FILE) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save state file {path}: {e}")


def can_send_signal(sig: TradingSignal, state: dict, now_utc: Optional[datetime] = None) -> Tuple[bool, str]:
    """Check bar dedup and 120-min same-direction cooldown."""
    now = now_utc or datetime.now(timezone.utc)
    if sig.candle_ts and state.get("last_engine_bar", {}).get(sig.strategy_name) == sig.candle_ts:
        return False, f"تکراری برای کندل {sig.candle_ts}"

    last_iso = state.get("last_dir_utc", {}).get(sig.direction)
    if last_iso:
        try:
            last_dt = datetime.fromisoformat(last_iso)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed_min = (now - last_dt).total_seconds() / 60.0
            if elapsed_min < DEDUP_MINUTES:
                return False, f"کول‌داون {DEDUP_MINUTES} دقیقه‌ای جهت {sig.direction} ({elapsed_min:.0f} دقیقه گذشته)"
        except Exception:
            pass
    return True, ""


def record_signal(sig: TradingSignal, state: dict, now_utc: Optional[datetime] = None) -> None:
    now = now_utc or datetime.now(timezone.utc)
    state.setdefault("last_dir_utc", {})[sig.direction] = now.isoformat()
    if sig.candle_ts:
        state.setdefault("last_engine_bar", {})[sig.strategy_name] = sig.candle_ts


# ── Macro Trend Helper ───────────────────────────────────────────────────────

def get_htf_bias(df4h: pd.DataFrame, df1h: pd.DataFrame) -> Tuple[Optional[str], str]:
    """
    Evaluate strict 4H + 1H macro trend on last closed candles (iloc[-2]).
    Returns (direction | None, human-readable Persian status).
    """
    if len(df4h) < 205 or len(df1h) < 205:
        return None, "داده کافی برای روند کلان نیست"

    r4 = df4h.iloc[-2]
    r1 = df1h.iloc[-2]

    vals = [r4["close"], r4["ema_50"], r4["ema_200"], r1["close"], r1["ema_20"], r1["ema_50"], r1["ema_200"]]
    if any(pd.isna(v) for v in vals):
        return None, "اندیکاتورهای کلان هنوز آماده نیستند"

    up = (
        r4["close"] > r4["ema_200"]
        and r4["ema_50"] > r4["ema_200"]
        and r1["ema_20"] > r1["ema_50"]
        and r1["close"] > r1["ema_200"]
    )
    dn = (
        r4["close"] < r4["ema_200"]
        and r4["ema_50"] < r4["ema_200"]
        and r1["ema_20"] < r1["ema_50"]
        and r1["close"] < r1["ema_200"]
    )

    if up:
        return "BUY", "روند کلان 4H+1H: صعودی هم‌راستا 🟢"
    if dn:
        return "SELL", "روند کلان 4H+1H: نزولی هم‌راستا 🔴"
    return None, "روند کلان 4H و 1H ناهماهنگ ⚪"


# ── Shared Signal Constructor ────────────────────────────────────────────────

def _build_ltf_signal(
    direction: str,
    live_price: float,
    bar_close: float,
    atr: float,
    sl_mult: float,
    rr: float,
    timeframe: str,
    strategy_name: str,
    candle_ts: str,
    win_prob: float,
    checks: List[Check],
) -> Optional[TradingSignal]:
    """Validate ATR & entry drift, compute SL/TP, and return TradingSignal."""
    if math.isnan(atr) or atr <= 0:
        return None

    # Protect against late entry if price already ran > 0.6*ATR away from signal bar close
    if abs(live_price - bar_close) > 0.6 * atr:
        logger.info(f"{strategy_name} skipped: price drifted ({live_price} vs close {bar_close}, ATR={atr:.2f})")
        return None

    sl_dist = sl_mult * atr
    if direction == "BUY":
        sl = round(live_price - sl_dist, 2)
        tp = round(live_price + rr * sl_dist, 2)
    else:
        sl = round(live_price + sl_dist, 2)
        tp = round(live_price - rr * sl_dist, 2)

    passed = sum(1 for c in checks if c.passed)
    return TradingSignal(
        direction=direction,
        entry=round(live_price, 2),
        stop_loss=sl,
        take_profit=tp,
        rr_ratio=round(rr, 2),
        win_probability=win_prob,
        checks=checks,
        confluence=passed,
        total_checks=len(checks),
        timeframe=timeframe,
        strategy_name=strategy_name,
        candle_ts=candle_ts,
    )


def _is_candle_fresh(candle_ts: pd.Timestamp, max_age_minutes: int) -> bool:
    """Verify the closed candle is recent (avoid firing stale signals on weekend/market halt)."""
    try:
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        age_min = (now_naive - candle_ts.to_pydatetime()).total_seconds() / 60.0
        return age_min <= max_age_minutes
    except Exception:
        return True


# ── Individual LTF Engines ───────────────────────────────────────────────────

def _check_30m_precision(df30m: pd.DataFrame, htf_dir: Optional[str], live_price: float) -> Optional[TradingSignal]:
    if htf_dir is None or len(df30m) < 35:
        return None
    ts = df30m.index[-2]
    if not _is_candle_fresh(ts, max_age_minutes=65):
        return None

    r, p = df30m.iloc[-2], df30m.iloc[-3]
    atr = float(r["atr"])

    if htf_dir == "BUY" and r["close"] > r["open"] and r["rsi"] < 64:
        sr_cross = p["stoch_k"] <= p["stoch_d"] and r["stoch_k"] > r["stoch_d"] and min(p["stoch_k"], r["stoch_k"]) < 0.35
        rsi7_dip = p["rsi_7"] < 35 and r["rsi_7"] > p["rsi_7"]
        if sr_cross or rsi7_dip:
            checks = [
                Check("روند کلان 4H+1H", True, "صعودی هم‌راستا ✅", 2.0),
                Check("مومنتوم StochRSI (30M)", sr_cross, f"تقاطع صعودی از اشباع ({r['stoch_k']:.2f})" if sr_cross else "غیرفعال"),
                Check("واکنش RSI(7) (30M)", rsi7_dip, f"برگشت از {p['rsi_7']:.1f} به {r['rsi_7']:.1f} ✅" if rsi7_dip else f"RSI7={r['rsi_7']:.1f}"),
                Check("کندل تایید (30M)", True, "کندل بسته‌شده صعودی ✅"),
            ]
            return _build_ltf_signal("BUY", live_price, float(r["close"]), atr, 1.5, 1.5, "4H + 1H + 30M", "پولبک دقیق 30M", str(ts), 61.0, checks)

    if htf_dir == "SELL" and r["close"] < r["open"] and r["rsi"] > 36:
        sr_cross = p["stoch_k"] >= p["stoch_d"] and r["stoch_k"] < r["stoch_d"] and max(p["stoch_k"], r["stoch_k"]) > 0.65
        rsi7_pop = p["rsi_7"] > 65 and r["rsi_7"] < p["rsi_7"]
        if sr_cross or rsi7_pop:
            checks = [
                Check("روند کلان 4H+1H", True, "نزولی هم‌راستا ✅", 2.0),
                Check("مومنتوم StochRSI (30M)", sr_cross, f"تقاطع نزولی از اشباع ({r['stoch_k']:.2f})" if sr_cross else "غیرفعال"),
                Check("واکنش RSI(7) (30M)", rsi7_pop, f"برگشت از {p['rsi_7']:.1f} به {r['rsi_7']:.1f} ✅" if rsi7_pop else f"RSI7={r['rsi_7']:.1f}"),
                Check("کندل تایید (30M)", True, "کندل بسته‌شده نزولی ✅"),
            ]
            return _build_ltf_signal("SELL", live_price, float(r["close"]), atr, 1.5, 1.5, "4H + 1H + 30M", "پولبک دقیق 30M", str(ts), 61.0, checks)

    return None


def _check_bb_stoch_pullback(
    df: pd.DataFrame, htf_dir: Optional[str], live_price: float,
    tf_label: str, strat_name: str, max_age_min: int, sl_mult: float = 1.8, rr: float = 1.8, win_prob: float = 59.0,
) -> Optional[TradingSignal]:
    """Shared BB/Stoch/StochRSI pullback checker used by both 15M_Sniper and 5M_Sniper."""
    if htf_dir is None or len(df) < 35:
        return None
    ts = df.index[-2]
    if not _is_candle_fresh(ts, max_age_minutes=max_age_min):
        return None

    r, p = df.iloc[-2], df.iloc[-3]
    atr = float(r["atr"])

    if htf_dir == "BUY" and r["close"] > r["open"] and r["rsi"] < 62:
        bb_dip  = min(p["low"], r["low"]) <= r["bb_middle"] - 0.35 * (r["bb_middle"] - r["bb_lower"])
        st_turn = p["osc_k"] <= p["osc_d"] and r["osc_k"] > r["osc_d"] and min(p["osc_k"], r["osc_k"]) < 42
        sr_turn = p["stoch_k"] <= p["stoch_d"] and r["stoch_k"] > r["stoch_d"] and min(p["stoch_k"], r["stoch_k"]) < 0.30
        if bb_dip or st_turn or sr_turn:
            checks = [
                Check("روند کلان 4H+1H", True, "صعودی تاییدشده ✅", 2.0),
                Check(f"برخورد باند بولینگر ({tf_label})", bb_dip, "پولبک به نیمه پایین BB ✅" if bb_dip else "در محدوده میانی"),
                Check(f"کراس استوکاستیک ({tf_label})", st_turn or sr_turn, f"Stoch K={r['osc_k']:.1f} > D ✅" if (st_turn or sr_turn) else f"Stoch={r['osc_k']:.1f}"),
                Check(f"RSI مناسب ورود ({tf_label})", True, f"RSI={r['rsi']:.1f} < 62 ✅"),
            ]
            return _build_ltf_signal("BUY", live_price, float(r["close"]), atr, sl_mult, rr, f"4H + 1H + {tf_label}", strat_name, str(ts), win_prob, checks)

    if htf_dir == "SELL" and r["close"] < r["open"] and r["rsi"] > 38:
        bb_pop  = max(p["high"], r["high"]) >= r["bb_middle"] + 0.35 * (r["bb_upper"] - r["bb_middle"])
        st_turn = p["osc_k"] >= p["osc_d"] and r["osc_k"] < r["osc_d"] and max(p["osc_k"], r["osc_k"]) > 58
        sr_turn = p["stoch_k"] >= p["stoch_d"] and r["stoch_k"] < r["stoch_d"] and max(p["stoch_k"], r["stoch_k"]) > 0.70
        if bb_pop or st_turn or sr_turn:
            checks = [
                Check("روند کلان 4H+1H", True, "نزولی تاییدشده ✅", 2.0),
                Check(f"برخورد باند بولینگر ({tf_label})", bb_pop, "پولبک به نیمه بالا BB ✅" if bb_pop else "در محدوده میانی"),
                Check(f"کراس استوکاستیک ({tf_label})", st_turn or sr_turn, f"Stoch K={r['osc_k']:.1f} < D ✅" if (st_turn or sr_turn) else f"Stoch={r['osc_k']:.1f}"),
                Check(f"RSI مناسب ورود ({tf_label})", True, f"RSI={r['rsi']:.1f} > 38 ✅"),
            ]
            return _build_ltf_signal("SELL", live_price, float(r["close"]), atr, sl_mult, rr, f"4H + 1H + {tf_label}", strat_name, str(ts), win_prob, checks)

    return None


def _check_15m_3candle(df15m: pd.DataFrame, htf_dir: Optional[str], live_price: float) -> Optional[TradingSignal]:
    """3-Candle + EMA200 + Stochastic inside confirmed 4H+1H trend on 15M."""
    if htf_dir is None or len(df15m) < 205:
        return None
    ts = df15m.index[-2]
    if not _is_candle_fresh(ts, max_age_minutes=40):
        return None

    r, p, p2, p3 = df15m.iloc[-2], df15m.iloc[-3], df15m.iloc[-4], df15m.iloc[-5]
    atr = float(r["atr"])

    is_bull3 = (p2["close"] > p2["open"]) and (p["close"] > p["open"]) and (r["close"] > r["open"]) and not (p3["close"] > p3["open"])
    is_bear3 = (p2["close"] < p2["open"]) and (p["close"] < p["open"]) and (r["close"] < r["open"]) and not (p3["close"] < p3["open"])

    if htf_dir == "BUY" and is_bull3 and r["close"] > r["ema_200"] and r["osc_k"] > r["osc_d"] and r["rsi"] < 66:
        checks = [
            Check("روند کلان 4H+1H", True, "صعودی هم‌راستا ✅", 2.0),
            Check("الگوی ۳ کندل صعودی (15M)", True, "۳ کندل متوالی بالای EMA200 ✅"),
            Check("استوکاستیک (15M)", True, f"K={r['osc_k']:.1f} > D={r['osc_d']:.1f} ✅"),
            Check("RSI (15M)", True, f"RSI={r['rsi']:.1f} < 66 ✅"),
        ]
        return _build_ltf_signal("BUY", live_price, float(r["close"]), atr, 1.5, 2.0, "4H + 1H + 15M", "۳ کندلی + استوکاستیک (15M)", str(ts), 58.0, checks)

    if htf_dir == "SELL" and is_bear3 and r["close"] < r["ema_200"] and r["osc_k"] < r["osc_d"] and r["rsi"] > 34:
        checks = [
            Check("روند کلان 4H+1H", True, "نزولی هم‌راستا ✅", 2.0),
            Check("الگوی ۳ کندل نزولی (15M)", True, "۳ کندل متوالی زیر EMA200 ✅"),
            Check("استوکاستیک (15M)", True, f"K={r['osc_k']:.1f} < D={r['osc_d']:.1f} ✅"),
            Check("RSI (15M)", True, f"RSI={r['rsi']:.1f} > 34 ✅"),
        ]
        return _build_ltf_signal("SELL", live_price, float(r["close"]), atr, 1.5, 2.0, "4H + 1H + 15M", "۳ کندلی + استوکاستیک (15M)", str(ts), 58.0, checks)

    return None


def _check_15m_rsi7(df15m: pd.DataFrame, htf_dir: Optional[str], live_price: float) -> Optional[TradingSignal]:
    """Fast RSI(7) extreme bounce on 15M aligned with 4H+1H trend."""
    if htf_dir is None or len(df15m) < 35:
        return None
    ts = df15m.index[-2]
    if not _is_candle_fresh(ts, max_age_minutes=40):
        return None

    r, p = df15m.iloc[-2], df15m.iloc[-3]
    atr = float(r["atr"])

    if htf_dir == "BUY" and p["rsi_7"] < 32 and r["rsi_7"] > p["rsi_7"] and r["close"] > r["open"]:
        checks = [
            Check("روند کلان 4H+1H", True, "صعودی هم‌راستا ✅", 2.0),
            Check("اشباع RSI(7) (15M)", True, f"برگشت از {p['rsi_7']:.1f} به {r['rsi_7']:.1f} ✅"),
            Check("کندل تایید (15M)", True, "کندل بسته‌شده صعودی ✅"),
        ]
        return _build_ltf_signal("BUY", live_price, float(r["close"]), atr, 1.8, 1.5, "4H + 1H + 15M", "شکار کف RSI(7) (15M)", str(ts), 60.0, checks)

    if htf_dir == "SELL" and p["rsi_7"] > 68 and r["rsi_7"] < p["rsi_7"] and r["close"] < r["open"]:
        checks = [
            Check("روند کلان 4H+1H", True, "نزولی هم‌راستا ✅", 2.0),
            Check("اشباع RSI(7) (15M)", True, f"برگشت از {p['rsi_7']:.1f} به {r['rsi_7']:.1f} ✅"),
            Check("کندل تایید (15M)", True, "کندل بسته‌شده نزولی ✅"),
        ]
        return _build_ltf_signal("SELL", live_price, float(r["close"]), atr, 1.8, 1.5, "4H + 1H + 15M", "شکار سقف RSI(7) (15M)", str(ts), 60.0, checks)

    return None


# ── Unified Portfolio Scanner ────────────────────────────────────────────────

def scan_all_engines(
    df4h: pd.DataFrame,
    df1h: pd.DataFrame,
    df30m: pd.DataFrame,
    df15m: pd.DataFrame,
    df5m: pd.DataFrame,
    live_price: float,
) -> Tuple[List[TradingSignal], str, str]:
    """
    Evaluate all 4 timeframe engines in priority order (1H -> 30M -> 15M -> 5M).
    Returns (valid_signals, htf_bias_text, primary_1h_reason).
    """
    htf_dir, htf_text = get_htf_bias(df4h, df1h)
    candidates: List[TradingSignal] = []

    # 1. 1H Macro Confluence (Priority 1)
    sig_1h = generate_signal(df4h, df1h, df30m, current_price=live_price)
    if sig_1h.direction in ("BUY", "SELL"):
        sig_1h.candle_ts = str(df1h.index[-2])
        sig_1h.timeframe = "4H + 1H + 30M"
        sig_1h.strategy_name = "همگرایی جامع (1H)"
        candidates.append(sig_1h)

    # 2. 30M Precision Dip (Priority 2)
    sig_30 = _check_30m_precision(df30m, htf_dir, live_price)
    if sig_30:
        candidates.append(sig_30)

    # 3. 15M Engines (Priority 3)
    sig_15_bb = _check_bb_stoch_pullback(df15m, htf_dir, live_price, "15M", "اسنایپر پولبک (15M)", max_age_min=40, sl_mult=1.8, rr=1.8, win_prob=58.5)
    if sig_15_bb:
        candidates.append(sig_15_bb)
    else:
        sig_15_3c = _check_15m_3candle(df15m, htf_dir, live_price)
        if sig_15_3c:
            candidates.append(sig_15_3c)
        else:
            sig_15_r7 = _check_15m_rsi7(df15m, htf_dir, live_price)
            if sig_15_r7:
                candidates.append(sig_15_r7)

    # 4. 5M Sniper Pullback (Priority 4)
    sig_5_bb = _check_bb_stoch_pullback(df5m, htf_dir, live_price, "5M", "اسکالپ دقیق (5M)", max_age_min=20, sl_mult=1.8, rr=1.8, win_prob=59.5)
    if sig_5_bb:
        candidates.append(sig_5_bb)

    return candidates, htf_text, sig_1h.skip_reason
