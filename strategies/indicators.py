"""
Technical indicators for Gold analysis.
Covers: EMA 20/50/200, RSI, MACD, Bollinger Bands,
        ATR, ADX, Stochastic RSI, Swing S/R levels.
"""
import pandas as pd
import numpy as np
from ta.trend      import EMAIndicator, MACD, ADXIndicator
from ta.momentum   import RSIIndicator, StochRSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to OHLCV DataFrame."""
    df = df.copy()
    c = df["close"]
    h = df["high"]
    l = df["low"]

    # ── Trend EMAs ────────────────────────────────────────────────
    df["ema_20"]  = EMAIndicator(c, window=20).ema_indicator()
    df["ema_50"]  = EMAIndicator(c, window=50).ema_indicator()
    df["ema_200"] = EMAIndicator(c, window=200).ema_indicator()

    # ── Momentum ──────────────────────────────────────────────────
    df["rsi"] = RSIIndicator(c, window=14).rsi()

    macd = MACD(c, window_fast=12, window_slow=26, window_sign=9)
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    stoch = StochRSIIndicator(c, window=14, smooth1=3, smooth2=3)
    df["stoch_k"] = stoch.stochrsi_k()
    df["stoch_d"] = stoch.stochrsi_d()

    # ── Volatility ────────────────────────────────────────────────
    bb = BollingerBands(c, window=20, window_dev=2)
    df["bb_upper"]  = bb.bollinger_hband()
    df["bb_lower"]  = bb.bollinger_lband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_pct"]    = bb.bollinger_pband()   # 0 = lower, 1 = upper

    df["atr"] = AverageTrueRange(h, l, c, window=14).average_true_range()

    # ── Trend Strength (ADX) ──────────────────────────────────────
    adx = ADXIndicator(h, l, c, window=14)
    df["adx"]    = adx.adx()
    df["adx_pos"] = adx.adx_pos()   # +DI
    df["adx_neg"] = adx.adx_neg()   # -DI

    return df


def find_swing_levels(df: pd.DataFrame, lookback: int = 120):
    """
    Find recent swing highs and lows using 5-bar fractals.
    Returns (supports, resistances) sorted ascending so nearest levels to entry are preserved.
    """
    highs = df["high"].tail(lookback)
    lows  = df["low"].tail(lookback)

    swing_highs, swing_lows = [], []
    vals_h = highs.values
    vals_l = lows.values

    for i in range(2, len(vals_h) - 2):
        if vals_h[i] > vals_h[i-1] and vals_h[i] > vals_h[i-2] \
                and vals_h[i] > vals_h[i+1] and vals_h[i] > vals_h[i+2]:
            swing_highs.append(round(float(vals_h[i]), 2))
        if vals_l[i] < vals_l[i-1] and vals_l[i] < vals_l[i-2] \
                and vals_l[i] < vals_l[i+1] and vals_l[i] < vals_l[i+2]:
            swing_lows.append(round(float(vals_l[i]), 2))

    swing_highs = sorted(set(swing_highs))
    swing_lows  = sorted(set(swing_lows))

    return swing_lows, swing_highs   # supports, resistances
