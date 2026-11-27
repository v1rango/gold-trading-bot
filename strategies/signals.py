"""
Gold signal engine — multi-timeframe confluence analysis.
8 checks across 4H / 1H / 30M timeframes.
Only produces a signal when:
  • confluence score >= MIN_CONFLUENCE (6/8)
  • R:R >= MIN_RR_RATIO (2.0)
  • ADX >= ADX_TREND_MIN (20)  → not a choppy market
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd

from config import (
    ATR_SL_MULT, MIN_CONFLUENCE, MIN_RR_RATIO, ADX_TREND_MIN,
)
from strategies.indicators import find_swing_levels


# ─── data classes ────────────────────────────────────────────────────────────

@dataclass
class Check:
    name:      str
    passed:    bool
    detail:    str
    weight:    float = 1.0   # importance multiplier


@dataclass
class TradingSignal:
    direction:       str           # 'BUY' | 'SELL' | 'NONE'
    entry:           float
    stop_loss:       float
    take_profit:     float
    rr_ratio:        float
    win_probability: float         # percentage, e.g. 68.0
    checks:          List[Check]   = field(default_factory=list)
    confluence:      int           = 0
    total_checks:    int           = 8
    skip_reason:     str           = ""
    timeframe:       str           = "4H+1H+30M"
    strategy_name:   str           = "همگرایی چندتایم‌فریم (1H)"
    candle_ts:       str           = ""
    signal_num:      Optional[int] = None


# ─── individual checks (return Check objects) ─────────────────────────────────

def chk_4h_trend(df4h: pd.DataFrame, direction: str) -> Check:
    """4H: price vs EMA200 and EMA50 alignment on last closed candle (mandatory macro trend filter)."""
    r = df4h.iloc[-2]
    price = r["close"]
    ema50, ema200 = r["ema_50"], r["ema_200"]

    if direction == "BUY":
        ok = price > ema200 and ema50 > ema200
        detail = (f"قیمت بالای EMA200 ✅ | EMA50>EMA200 ✅"
                  if ok else
                  f"قیمت زیر EMA200 یا EMA50<EMA200 ❌")
    else:
        ok = price < ema200 and ema50 < ema200
        detail = (f"قیمت زیر EMA200 ✅ | EMA50<EMA200 ✅"
                  if ok else
                  f"روند ۴ ساعته نزولی نیست ❌")

    return Check("روند 4H (EMA200)", ok, detail, weight=2.0)


def chk_1h_ema(df1h: pd.DataFrame, direction: str) -> Check:
    """1H: EMA20 vs EMA50 on last closed candle."""
    curr, prev = df1h.iloc[-2], df1h.iloc[-3]

    if direction == "BUY":
        ok = curr["ema_20"] > curr["ema_50"]
        cross = (prev["ema_20"] <= prev["ema_50"] and
                 curr["ema_20"] >  curr["ema_50"])
        detail = ("🌟 Golden Cross اخیر!" if cross else
                  "EMA20 بالای EMA50" if ok else
                  "EMA20 زیر EMA50 ❌")
    else:
        ok = curr["ema_20"] < curr["ema_50"]
        cross = (prev["ema_20"] >= prev["ema_50"] and
                 curr["ema_20"] <  curr["ema_50"])
        detail = ("💀 Death Cross اخیر!" if cross else
                  "EMA20 زیر EMA50" if ok else
                  "EMA20 بالای EMA50 ❌")

    return Check("EMA 20/50 (1H)", ok, detail)


def chk_1h_rsi(df1h: pd.DataFrame, direction: str) -> Check:
    """1H: RSI position for entry on last closed candle."""
    rsi = df1h.iloc[-2]["rsi"]

    if direction == "BUY":
        ok = 30 <= rsi <= 60     # not overbought, decent entry zone
        detail = f"RSI={rsi:.1f} {'✅ مناسب ورود' if ok else '❌ اشباع خرید یا خیلی پایین'}"
    else:
        ok = 40 <= rsi <= 70     # not oversold, decent short entry
        detail = f"RSI={rsi:.1f} {'✅ مناسب ورود' if ok else '❌ اشباع فروش یا خیلی بالا'}"

    return Check("RSI 14 (1H)", ok, detail)


def chk_1h_macd(df1h: pd.DataFrame, direction: str) -> Check:
    """1H: MACD vs signal line on last closed candle."""
    curr, prev = df1h.iloc[-2], df1h.iloc[-3]
    cross_up   = prev["macd"] <= prev["macd_signal"] and curr["macd"] > curr["macd_signal"]
    cross_down = prev["macd"] >= prev["macd_signal"] and curr["macd"] < curr["macd_signal"]

    if direction == "BUY":
        if cross_up:
            return Check("MACD (1H)", True,  "✅ تازه از Signal Line عبور کرد ⬆️", weight=1.5)
        ok = curr["macd"] > curr["macd_signal"] and curr["macd_hist"] > 0
        detail = "MACD بالای Signal ✅" if ok else "MACD زیر Signal ❌"
    else:
        if cross_down:
            return Check("MACD (1H)", True,  "✅ تازه زیر Signal Line افتاد ⬇️", weight=1.5)
        ok = curr["macd"] < curr["macd_signal"] and curr["macd_hist"] < 0
        detail = "MACD زیر Signal ✅" if ok else "MACD بالای Signal ❌"

    return Check("MACD (1H)", ok, detail)


def chk_1h_bb(df1h: pd.DataFrame, direction: str) -> Check:
    """1H: Bollinger Bands position on last closed candle."""
    r    = df1h.iloc[-2]
    pct  = r["bb_pct"]          # 0 = lower band, 1 = upper band

    if direction == "BUY":
        ok = pct < 0.40          # price in lower half → room to rise
        detail = f"BB% = {pct:.2f} {'✅ نزدیک باند پایین' if ok else '❌ نزدیک باند بالا'}"
    else:
        ok = pct > 0.60          # price in upper half → room to fall
        detail = f"BB% = {pct:.2f} {'✅ نزدیک باند بالا' if ok else '❌ نزدیک باند پایین'}"

    return Check("Bollinger Bands (1H)", ok, detail)


def chk_1h_adx(df1h: pd.DataFrame, direction: str) -> Check:
    """1H: ADX trend strength + directional alignment on last closed candle."""
    r   = df1h.iloc[-2]
    adx = r["adx"]
    trending = adx >= ADX_TREND_MIN

    if direction == "BUY":
        aligned = r["adx_pos"] > r["adx_neg"]
        ok = trending and aligned
        detail = (f"ADX={adx:.1f} ✅ روند قوی صعودی (+DI>{r['adx_neg']:.1f})"
                  if ok else
                  f"ADX={adx:.1f} ❌ {'بدون روند' if not trending else 'جهت نزولی'}")
    else:
        aligned = r["adx_neg"] > r["adx_pos"]
        ok = trending and aligned
        detail = (f"ADX={adx:.1f} ✅ روند قوی نزولی (-DI>{r['adx_pos']:.1f})"
                  if ok else
                  f"ADX={adx:.1f} ❌ {'بدون روند' if not trending else 'جهت صعودی'}")

    return Check("ADX (1H)", ok, detail, weight=1.5)


def chk_30m_stoch(df30m: pd.DataFrame, direction: str) -> Check:
    """30M: Stochastic RSI crossover on last closed candle."""
    curr, prev = df30m.iloc[-2], df30m.iloc[-3]
    k, d = curr["stoch_k"], curr["stoch_d"]

    if direction == "BUY":
        cross_up = prev["stoch_k"] <= prev["stoch_d"] and curr["stoch_k"] > curr["stoch_d"]
        oversold = k < 0.20
        ok = oversold or cross_up
        detail = (f"Stoch K={k:.2f} ✅ {'تقاطع صعودی' if cross_up else 'اشباع فروش'}"
                  if ok else f"Stoch K={k:.2f} ❌ خنثی یا اشباع خرید")
    else:
        cross_dn = prev["stoch_k"] >= prev["stoch_d"] and curr["stoch_k"] < curr["stoch_d"]
        overbought = k > 0.80
        ok = overbought or cross_dn
        detail = (f"Stoch K={k:.2f} ✅ {'تقاطع نزولی' if cross_dn else 'اشباع خرید'}"
                  if ok else f"Stoch K={k:.2f} ❌ خنثی یا اشباع فروش")

    return Check("Stochastic RSI (30M)", ok, detail)


def chk_30m_rsi(df30m: pd.DataFrame, direction: str) -> Check:
    """30M: RSI confirmation of entry timing on last closed candle."""
    rsi = df30m.iloc[-2]["rsi"]

    if direction == "BUY":
        ok = rsi < 55
        detail = f"RSI 30M = {rsi:.1f} {'✅ فضا برای رشد' if ok else '❌ خیلی بالاست'}"
    else:
        ok = rsi > 45
        detail = f"RSI 30M = {rsi:.1f} {'✅ فضا برای افت' if ok else '❌ خیلی پایینه'}"

    return Check("RSI 14 (30M)", ok, detail)


# ─── SL / TP / R:R ───────────────────────────────────────────────────────────

def calculate_trade_levels(direction: str, entry: float, atr: float,
                            supports: list, resistances: list) -> dict:
    """
    ATR-based SL, then find best TP target.
    Returns dict with sl, tp, rr.
    """
    sl_dist = atr * ATR_SL_MULT

    if direction == "BUY":
        sl = entry - sl_dist
        # Look for nearest resistance above entry that offers at least MIN_RR_RATIO
        candidates = [r for r in resistances if (r - entry) >= sl_dist * MIN_RR_RATIO]
        if candidates:
            tp = min(candidates)
            rr = (tp - entry) / sl_dist
        else:
            tp = entry + sl_dist * MIN_RR_RATIO
            rr = MIN_RR_RATIO
    else:
        sl = entry + sl_dist
        # Look for nearest support below entry that offers at least MIN_RR_RATIO
        candidates = [s for s in supports if (entry - s) >= sl_dist * MIN_RR_RATIO]
        if candidates:
            tp = max(candidates)
            rr = (entry - tp) / sl_dist
        else:
            tp = entry - sl_dist * MIN_RR_RATIO
            rr = MIN_RR_RATIO

    return {"sl": round(sl, 2), "tp": round(tp, 2), "rr": round(rr, 2)}


# ─── win probability ──────────────────────────────────────────────────────────

def estimate_win_probability(checks: List[Check], rr: float) -> float:
    """
    Weighted confluence -> calibrated win probability estimate (55%-76% range).
    """
    total_weight = sum(c.weight for c in checks)
    passed_weight = sum(c.weight for c in checks if c.passed)
    confluence_ratio = passed_weight / total_weight if total_weight > 0 else 0

    base = 40.0 + confluence_ratio * 32.0

    if rr >= 3.0:
        base += 4.0
    elif rr >= 2.5:
        base += 2.0

    return round(min(base, 78.0), 1)


# ─── main signal generator ────────────────────────────────────────────────────

def generate_signal(df4h: pd.DataFrame,
                    df1h: pd.DataFrame,
                    df30m: pd.DataFrame,
                    current_price: Optional[float] = None) -> TradingSignal:
    """
    Run all 8 checks for BUY and SELL.
    Requires:
      • ADX >= ADX_TREND_MIN with directional alignment
      • 4H macro trend alignment (never trade against 4H trend)
      • confluence >= MIN_CONFLUENCE (6/8)
      • R:R >= MIN_RR_RATIO (2.0)
    Always returns TradingSignal (with direction='NONE' and skip_reason if filtered).
    """
    import math

    if len(df4h) < 3 or len(df1h) < 3 or len(df30m) < 3:
        fallback_entry = float(current_price) if current_price is not None and current_price > 0 else 0.0
        return TradingSignal("NONE", fallback_entry, 0, 0, 0, 0,
                             skip_reason="داده کافی برای تحلیل نیست")

    curr_1h = df1h.iloc[-2]
    entry   = float(current_price) if current_price is not None and current_price > 0 else float(curr_1h["close"])
    atr     = float(curr_1h["atr"])
    adx     = float(curr_1h["adx"])

    if math.isnan(atr) or atr <= 0:
        return TradingSignal("NONE", entry, 0, 0, 0, 0,
                             skip_reason="ATR نامعتبر است")

    if math.isnan(adx) or adx < ADX_TREND_MIN:
        return TradingSignal("NONE", entry, 0, 0, 0, 0,
                             skip_reason=f"بازار رنج است (ADX={adx:.1f} < {ADX_TREND_MIN})")

    supports, resistances = find_swing_levels(df1h.iloc[:-1], lookback=120)

    best: Optional[TradingSignal] = None
    scores = {}

    for direction in ("BUY", "SELL"):
        c4   = chk_4h_trend(df4h,  direction)
        cadx = chk_1h_adx  (df1h,  direction)
        checks = [
            c4,
            chk_1h_ema  (df1h,  direction),
            chk_1h_rsi  (df1h,  direction),
            chk_1h_macd (df1h,  direction),
            chk_1h_bb   (df1h,  direction),
            cadx,
            chk_30m_stoch(df30m, direction),
            chk_30m_rsi (df30m, direction),
        ]

        passed = sum(1 for c in checks if c.passed)
        scores[direction] = passed

        # Strict quality gates: must align with 4H trend, directional ADX, and >= MIN_CONFLUENCE
        if not c4.passed or not cadx.passed or passed < MIN_CONFLUENCE:
            continue

        levels = calculate_trade_levels(direction, entry, atr, supports, resistances)
        if levels["rr"] < MIN_RR_RATIO:
            continue

        prob = estimate_win_probability(checks, levels["rr"])

        sig = TradingSignal(
            direction       = direction,
            entry           = round(entry, 2),
            stop_loss       = levels["sl"],
            take_profit     = levels["tp"],
            rr_ratio        = levels["rr"],
            win_probability = prob,
            checks          = checks,
            confluence      = passed,
            total_checks    = len(checks),
        )

        if best is None or passed > best.confluence:
            best = sig

    if best is not None:
        return best

    return TradingSignal(
        "NONE", entry, 0, 0, 0, 0,
        skip_reason=f"شرایط کامل نیست (خرید {scores['BUY']}/8 | فروش {scores['SELL']}/8 — حداقل {MIN_CONFLUENCE}/8 هم‌راستا با روند 4H لازم است)",
    )
