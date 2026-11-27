from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from bot.formatter import format_daily_summary, format_lifecycle_event, format_manual_status, format_signal
from bot.telegram_bot import TelegramBot, redact_secrets
import data.dashboard_export as dashboard_export
import data.gold as gold_data
import data.news as news_data
import scan_once
from strategies.backtester import _closed_slice_with_forming_tail, format_backtest_report, run_backtest
from strategies.multi_engine import can_send_signal, get_htf_bias, load_state, record_signal, save_state
from strategies.risk_guard import assess_market_risk
import strategies.scan_runner as scan_runner
from strategies.signals import Check, TradingSignal, generate_signal


def _make_ohlcv_df(
    rows: int = 230,
    start_utc: str = "2026-11-20 00:00:00",
    freq: str = "1h",
    base_price: float = 3500.0,
    step: float = 1.0,
) -> pd.DataFrame:
    idx = pd.date_range(start=start_utc, periods=rows, freq=freq)
    closes = np.array([base_price + i * step for i in range(rows)], dtype=float)
    opens = closes - (0.5 if step >= 0 else -0.5)
    highs = np.maximum(opens, closes) + 2.0
    lows = np.minimum(opens, closes) - 2.0
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.full(rows, 100.0),
        },
        index=idx,
    )


def _make_indicator_df(rows: int = 215, freq: str = "1h", bullish: bool = True) -> pd.DataFrame:
    idx = pd.date_range("2026-11-10 00:00:00", periods=rows, freq=freq)
    df = pd.DataFrame(index=idx)
    if bullish:
        df["open"] = 3590.0
        df["close"] = 3600.0
        df["high"] = 3605.0
        df["low"] = 3585.0
        df["ema_20"] = 3580.0
        df["ema_50"] = 3550.0
        df["ema_200"] = 3500.0
        df["rsi"] = 48.0
        df["rsi_7"] = 46.0
        df["macd"] = 3.0
        df["macd_signal"] = 2.0
        df["macd_hist"] = 1.0
        df["bb_upper"] = 3630.0
        df["bb_middle"] = 3605.0
        df["bb_lower"] = 3580.0
        df["bb_pct"] = 0.30
        df["atr"] = 10.0
        df["adx"] = 28.0
        df["adx_pos"] = 30.0
        df["adx_neg"] = 14.0
        df["stoch_k"] = 0.15
        df["stoch_d"] = 0.18
        df["osc_k"] = 30.0
        df["osc_d"] = 25.0
    else:
        df["open"] = 3410.0
        df["close"] = 3400.0
        df["high"] = 3415.0
        df["low"] = 3395.0
        df["ema_20"] = 3420.0
        df["ema_50"] = 3450.0
        df["ema_200"] = 3500.0
        df["rsi"] = 52.0
        df["rsi_7"] = 54.0
        df["macd"] = -3.0
        df["macd_signal"] = -2.0
        df["macd_hist"] = -1.0
        df["bb_upper"] = 3420.0
        df["bb_middle"] = 3395.0
        df["bb_lower"] = 3370.0
        df["bb_pct"] = 0.70
        df["atr"] = 10.0
        df["adx"] = 28.0
        df["adx_pos"] = 14.0
        df["adx_neg"] = 30.0
        df["stoch_k"] = 0.85
        df["stoch_d"] = 0.82
        df["osc_k"] = 70.0
        df["osc_d"] = 75.0
    return df


# ── 1. get_htf_bias & scan_runner HTF mapping ────────────────────────────────


def test_get_htf_bias_bullish_bearish_neutral_and_closed_candle():
    df4h_bull = _make_indicator_df(210, "4h", bullish=True)
    df1h_bull = _make_indicator_df(210, "1h", bullish=True)
    # Corrupt unclosed bar iloc[-1]; closed bar iloc[-2] must stay bullish
    df4h_bull.iloc[-1, df4h_bull.columns.get_loc("close")] = 3000.0
    df1h_bull.iloc[-1, df1h_bull.columns.get_loc("close")] = 3000.0

    direction, text = get_htf_bias(df4h_bull, df1h_bull)
    assert direction == "BUY"
    assert "صعودی" in text

    df4h_bear = _make_indicator_df(210, "4h", bullish=False)
    df1h_bear = _make_indicator_df(210, "1h", bullish=False)
    direction, text = get_htf_bias(df4h_bear, df1h_bear)
    assert direction == "SELL"
    assert "نزولی" in text

    # Misaligned 4H bull vs 1H bear
    direction, text = get_htf_bias(df4h_bull, df1h_bear)
    assert direction is None
    assert "ناهماهنگ" in text

    # Short dataframe
    direction, _ = get_htf_bias(df4h_bull.iloc[:100], df1h_bull)
    assert direction is None


def test_scan_runner_passes_normalized_htf_bias_and_df30m(monkeypatch, tmp_path):
    df4h = _make_indicator_df(210, "4h", bullish=False)
    df1h = _make_indicator_df(210, "1h", bullish=False)
    df30 = _make_indicator_df(60, "30min", bullish=False)
    df15 = _make_indicator_df(210, "15min", bullish=False)
    df5 = _make_indicator_df(60, "5min", bullish=False)

    monkeypatch.setattr(scan_runner, "get_gold_4h", lambda: df4h)
    monkeypatch.setattr(scan_runner, "get_gold_1h", lambda: df1h)
    monkeypatch.setattr(scan_runner, "get_gold_30m", lambda: df30)
    monkeypatch.setattr(scan_runner, "get_gold_15m", lambda: df15)
    monkeypatch.setattr(scan_runner, "get_gold_5m", lambda: df5)
    monkeypatch.setattr(scan_runner, "get_gold_price", lambda: {"price": 3400.0, "change_24h": -0.5, "source": "TEST"})
    monkeypatch.setattr(scan_runner, "calculate_indicators", lambda df: df)
    monkeypatch.setattr(scan_runner, "get_economic_calendar", lambda: [])
    monkeypatch.setattr(scan_runner, "scan_all_engines", lambda *a, **kw: ([], "روند کلان 4H+1H: نزولی هم‌راستا 🔴", "ok"))

    captured = {}

    def fake_export(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(scan_runner, "export_dashboard_snapshot", fake_export)
    monkeypatch.setattr(scan_runner, "save_state", lambda s: None)

    bot = MagicMock(spec=TelegramBot)
    scan_runner.run_gold_scan(bot, is_manual=False, state={})

    assert captured["htf_bias"] == "BEARISH"
    assert "نزولی" in captured["htf_text"]
    assert captured["df30m"] is df30


# ── 2. multi_engine dedup & cooldown ─────────────────────────────────────────


def test_multi_engine_dedup_and_cooldown(tmp_path):
    state_file = tmp_path / "state.json"
    state = load_state(str(state_file))
    t0 = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)

    sig1 = TradingSignal(
        direction="BUY",
        entry=3500.0,
        stop_loss=3485.0,
        take_profit=3530.0,
        rr_ratio=2.0,
        win_probability=65.0,
        checks=[Check("c1", True, "ok")],
        confluence=1,
        total_checks=1,
        strategy_name="اسنایپر پولبک (15M)",
        candle_ts="2026-11-26 09:45:00",
    )

    ok, _ = can_send_signal(sig1, state, now_utc=t0)
    assert ok is True
    record_signal(sig1, state, now_utc=t0)
    save_state(state, str(state_file))

    reloaded = load_state(str(state_file))

    # Same candle_ts + same engine -> blocked
    ok, reason = can_send_signal(sig1, reloaded, now_utc=t0 + timedelta(minutes=5))
    assert ok is False
    assert "تکراری" in reason

    # Different engine, same direction within 120m -> blocked by cooldown
    sig_other_engine = TradingSignal(
        direction="BUY",
        entry=3501.0,
        stop_loss=3486.0,
        take_profit=3531.0,
        rr_ratio=2.0,
        win_probability=65.0,
        strategy_name="اسکالپ دقیق (5M)",
        candle_ts="2026-11-26 09:55:00",
    )
    ok, reason = can_send_signal(sig_other_engine, reloaded, now_utc=t0 + timedelta(minutes=60))
    assert ok is False
    assert "کول‌داون" in reason

    # Opposite direction within 120m -> allowed
    sig_sell = TradingSignal(
        direction="SELL",
        entry=3501.0,
        stop_loss=3516.0,
        take_profit=3471.0,
        rr_ratio=2.0,
        win_probability=65.0,
        strategy_name="اسکالپ دقیق (5M)",
        candle_ts="2026-11-26 09:55:00",
    )
    ok, _ = can_send_signal(sig_sell, reloaded, now_utc=t0 + timedelta(minutes=30))
    assert ok is True

    # Same direction after >= 120m -> allowed
    ok, _ = can_send_signal(sig_other_engine, reloaded, now_utc=t0 + timedelta(minutes=config.DEDUP_MINUTES))
    assert ok is True


# ── 3. signals.py closed-candle evaluation ───────────────────────────────────


def test_1h_macro_uses_closed_candles_and_ignores_forming_bar():
    df4h = _make_indicator_df(210, "4h", bullish=True)
    df1h = _make_indicator_df(210, "1h", bullish=True)
    df30 = _make_indicator_df(210, "30min", bullish=True)

    # Make forming bar (iloc[-1]) look terrible (low ADX, bearish EMA)
    df1h.iloc[-1, df1h.columns.get_loc("adx")] = 5.0
    df1h.iloc[-1, df1h.columns.get_loc("ema_20")] = 3000.0
    df4h.iloc[-1, df4h.columns.get_loc("close")] = 3000.0
    df30.iloc[-1, df30.columns.get_loc("rsi")] = 90.0

    sig = generate_signal(df4h, df1h, df30, current_price=3600.0)
    assert sig.direction == "BUY"

    # Now mutate closed bar (iloc[-2]) ADX < 20 -> must filter out
    df1h.iloc[-2, df1h.columns.get_loc("adx")] = 12.0
    sig_filtered = generate_signal(df4h, df1h, df30, current_price=3600.0)
    assert sig_filtered.direction == "NONE"
    assert "ADX" in sig_filtered.skip_reason


# ── 4. data/gold.py yfinance UTC conversion & dedup ──────────────────────────


def test_fetch_yf_candles_converts_tz_to_utc_and_deduplicates(monkeypatch):
    ny_idx = pd.DatetimeIndex(
        [
            "2026-11-26 09:00:00-05:00",
            "2026-11-26 09:00:00-05:00",  # duplicate
            "2026-11-26 10:00:00-05:00",
        ]
    )
    raw_df = pd.DataFrame(
        {
            "Open": [3500.0, 3500.0, 3510.0],
            "High": [3505.0, 3506.0, 3515.0],
            "Low": [3495.0, 3494.0, 3505.0],
            "Close": [3502.0, 3504.0, 3512.0],
            "Volume": [10.0, 12.0, 15.0],
        },
        index=ny_idx,
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            return raw_df

    monkeypatch.setattr(gold_data.yf, "Ticker", FakeTicker)
    df = gold_data._fetch_yf_candles("1h", "5d")

    assert df.index.tz is None
    assert len(df) == 2
    assert list(df.index) == [pd.Timestamp("2026-11-26 14:00:00"), pd.Timestamp("2026-11-26 15:00:00")]
    assert df.iloc[0]["close"] == 3504.0  # kept last duplicate


# ── 5. dashboard_export._evaluate_open_signals & refresh_dashboard_from_cache


def test_evaluate_open_signals_ignores_pre_entry_5m_bars():
    idx = pd.DatetimeIndex(
        [
            "2026-11-26 10:00:00",  # BEFORE signal emitted at 10:04:30 -> must be ignored!
            "2026-11-26 10:05:00",  # starts AFTER 10:04:30 -> evaluated
            "2026-11-26 10:10:00",
        ]
    )
    df5m = pd.DataFrame(
        {
            "open": [3500.0, 3501.0, 3510.0],
            "high": [3502.0, 3512.0, 3535.0],
            "low": [3470.0, 3498.0, 3508.0],  # 10:00 bar dipped to 3470 (< SL 3485)!
            "close": [3501.0, 3510.0, 3530.0],
        },
        index=idx,
    )

    signals = [
        {
            "id": "sig_test_1",
            "timestamp_utc": "2026-11-26T10:04:30Z",
            "direction": "BUY",
            "entry": 3500.0,
            "stop_loss": 3485.0,
            "take_profit": 3530.0,
            "auto_outcome": "OPEN",
        }
    ]

    dashboard_export._evaluate_open_signals(signals, df5m)
    assert signals[0]["auto_outcome"] == "TP_HIT"

    # Also ensure a bar opening at 10:05:00 is ignored when signal is emitted at 10:05:15
    signals2 = [
        {
            "id": "sig_test_2",
            "timestamp_utc": "2026-11-26T10:05:15Z",
            "direction": "BUY",
            "entry": 3510.0,
            "stop_loss": 3500.0,
            "take_profit": 3550.0,
            "auto_outcome": "OPEN",
        }
    ]
    df5m_only_current = df5m.iloc[:2]  # 10:00 and 10:05 (low=3498 <= SL 3500)
    dashboard_export._evaluate_open_signals(signals2, df5m_only_current)
    assert signals2[0]["auto_outcome"] == "OPEN"


def test_dashboard_export_30m_and_refresh_updates_timestamps(monkeypatch, tmp_path):
    hist_path = tmp_path / "dashboard_history.json"
    out_path = tmp_path / "dashboard_data.json"
    monkeypatch.setattr(dashboard_export, "HISTORY_FILE", str(hist_path))
    monkeypatch.setattr(dashboard_export, "OUTPUT_JSON_PATH", out_path)

    sample_news = [
        {
            "title": "Core PCE",
            "country": "USD",
            "impact": "High",
            "date_utc": "2026-11-26T13:30:00Z",
            "tehran_date": "2026-11-26",
            "tehran_time": "17:00",
            "is_today": True,
            "is_past": False,
            "forecast": "0.3%",
            "previous": "0.3%",
            "actual": "",
        }
    ]
    monkeypatch.setattr(dashboard_export, "_fetch_economic_news", lambda existing=None: sample_news)

    df30m = _make_indicator_df(50, "30min", bullish=True)
    dashboard_export.export_dashboard_snapshot(
        price={"price": 3600.0, "change_24h": 0.4, "source": "OANDA:XAUUSD"},
        df30m=df30m,
        htf_bias="BULLISH",
        htf_text="صعودی",
        reason_1h="ok",
    )

    exported = json.loads(out_path.read_text(encoding="utf-8"))
    assert exported["market"]["htf_bias"] == "BULLISH"
    assert exported["market"]["indicators_30m"]["rsi"] == 48.0

    # Refresh cache without new price & same news -> returns False, still syncs history timestamps
    changed = dashboard_export.refresh_dashboard_from_cache()
    assert changed is False
    saved_hist = json.loads(hist_path.read_text(encoding="utf-8"))
    assert saved_hist["news_updated_utc"]
    assert saved_hist["updated_at_tehran"]

    # Refresh with explicit price -> returns True
    changed_with_price = dashboard_export.refresh_dashboard_from_cache({"price": 3605.0})
    assert changed_with_price is True


# ── 6. scan_once.py state dedup & config security ────────────────────────────


def test_scan_once_wakeup_and_sleep_dedup(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"

    def _load():
        return load_state(str(state_path))

    def _save(st):
        save_state(st, str(state_path))

    monkeypatch.setattr(scan_once, "load_state", _load)
    monkeypatch.setattr(scan_once, "save_state", _save)
    monkeypatch.setattr(scan_runner, "load_state", _load)
    monkeypatch.setattr(scan_runner, "save_state", _save)
    monkeypatch.setattr(scan_once, "get_gold_price", lambda: {"price": 3500.0, "change_24h": 0.1, "source": "TEST"})
    monkeypatch.setattr(scan_once, "refresh_dashboard_from_cache", lambda price=None: bool(price))

    bot = MagicMock(spec=TelegramBot)
    bot.send_message.return_value = True
    bot.get_main_keyboard.return_value = {}

    # 1) Sleep dedup: first call sends, second call on same Tehran day skips
    thursday_midnight = config.TIMEZONE.localize(datetime(2026, 11, 26, 0, 10))
    state = _load()
    sent1, deploy1 = scan_once.send_sleep_if_needed(bot, state, now=thursday_midnight)
    assert sent1 is True and deploy1 is True
    assert bot.send_message.call_count == 1

    sent2, deploy2 = scan_once.send_sleep_if_needed(bot, _load(), now=thursday_midnight + timedelta(minutes=5))
    assert sent2 is False and deploy2 is False
    assert bot.send_message.call_count == 1

    # 2) Wakeup dedup via --auto / run_gold_scan
    thursday_morning = config.TIMEZONE.localize(datetime(2026, 11, 26, 10, 5))
    assert scan_once.should_send_wakeup(_load(), now=thursday_morning) is True

    df4h = _make_indicator_df(210, "4h", bullish=True)
    df1h = _make_indicator_df(210, "1h", bullish=True)
    df30 = _make_indicator_df(60, "30min", bullish=True)
    df15 = _make_indicator_df(210, "15min", bullish=True)
    df5 = _make_indicator_df(60, "5min", bullish=True)
    monkeypatch.setattr(scan_runner, "get_gold_4h", lambda: df4h)
    monkeypatch.setattr(scan_runner, "get_gold_1h", lambda: df1h)
    monkeypatch.setattr(scan_runner, "get_gold_30m", lambda: df30)
    monkeypatch.setattr(scan_runner, "get_gold_15m", lambda: df15)
    monkeypatch.setattr(scan_runner, "get_gold_5m", lambda: df5)
    monkeypatch.setattr(scan_runner, "get_gold_price", lambda: {"price": 3600.0, "change_24h": 0.2, "source": "TEST"})
    monkeypatch.setattr(scan_runner, "calculate_indicators", lambda df: df)
    monkeypatch.setattr(scan_runner, "get_economic_calendar", lambda: [])
    monkeypatch.setattr(scan_runner, "scan_all_engines", lambda *a, **kw: ([], "خنثی", "ok"))
    monkeypatch.setattr(scan_runner, "export_dashboard_snapshot", lambda **kw: None)

    scan_once._run_auto_mode(bot, now=thursday_morning)
    assert bot.send_message.call_count == 2  # wakeup sent
    assert scan_once.should_send_wakeup(_load(), now=thursday_morning + timedelta(minutes=5)) is False

    # 3) Weekend skips scan and returns should_deploy=False when news unchanged
    saturday = config.TIMEZONE.localize(datetime(2026, 11, 28, 12, 0))
    assert scan_once._run_auto_mode(bot, now=saturday) is False
    assert bot.send_message.call_count == 2


def test_scan_once_cli_wakeup_and_sleep_write_github_output_and_dedup(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    gh_out = tmp_path / "gh_output.txt"

    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setattr(scan_once, "validate_telegram_config", lambda: ("999:TEST_TOKEN", ["111"]))
    monkeypatch.setattr(scan_once, "load_state", lambda: load_state(str(state_path)))
    monkeypatch.setattr(scan_once, "save_state", lambda st: save_state(st, str(state_path)))
    monkeypatch.setattr(scan_runner, "load_state", lambda: load_state(str(state_path)))
    monkeypatch.setattr(scan_runner, "save_state", lambda st: save_state(st, str(state_path)))
    monkeypatch.setattr(scan_once, "get_gold_price", lambda: {"price": 3500.0, "change_24h": 0.0, "source": "TEST"})
    monkeypatch.setattr(scan_once, "refresh_dashboard_from_cache", lambda price=None: bool(price))

    sent_messages = []

    class FakeBot:
        def __init__(self, token, chat_ids):
            self.token = token
            self.chat_ids = chat_ids

        def get_main_keyboard(self):
            return {}

        def get_scan_inline_keyboard(self):
            return {}

        def send_message(self, text, **kwargs):
            sent_messages.append(text)
            return True

    monkeypatch.setattr(scan_once, "TelegramBot", FakeBot)
    monkeypatch.setattr(scan_runner, "get_gold_4h", lambda: _make_indicator_df(210, "4h", bullish=True))
    monkeypatch.setattr(scan_runner, "get_gold_1h", lambda: _make_indicator_df(210, "1h", bullish=True))
    monkeypatch.setattr(scan_runner, "get_gold_30m", lambda: _make_indicator_df(60, "30min", bullish=True))
    monkeypatch.setattr(scan_runner, "get_gold_15m", lambda: _make_indicator_df(210, "15min", bullish=True))
    monkeypatch.setattr(scan_runner, "get_gold_5m", lambda: _make_indicator_df(60, "5min", bullish=True))
    monkeypatch.setattr(scan_runner, "get_gold_price", lambda: {"price": 3600.0, "change_24h": 0.2, "source": "TEST"})
    monkeypatch.setattr(scan_runner, "calculate_indicators", lambda df: df)
    monkeypatch.setattr(scan_runner, "get_economic_calendar", lambda: [])
    monkeypatch.setattr(scan_runner, "scan_all_engines", lambda *a, **kw: ([], "خنثی", "ok"))
    monkeypatch.setattr(scan_runner, "export_dashboard_snapshot", lambda **kw: None)

    monkeypatch.setattr(sys, "argv", ["scan_once.py", "--wakeup"])
    scan_once.main()
    assert len(sent_messages) == 1

    # Second --wakeup same day must NOT send duplicate wakeup
    monkeypatch.setattr(sys, "argv", ["scan_once.py", "--wakeup"])
    scan_once.main()
    assert len(sent_messages) == 1

    # First --sleep sends goodnight; second --sleep skips and sets should_deploy=false
    monkeypatch.setattr(sys, "argv", ["scan_once.py", "--sleep"])
    scan_once.main()
    assert len(sent_messages) == 2

    monkeypatch.setattr(sys, "argv", ["scan_once.py", "--sleep"])
    scan_once.main()
    assert len(sent_messages) == 2

    outputs = gh_out.read_text(encoding="utf-8").splitlines()
    assert outputs == [
        "should_deploy=true",
        "should_deploy=true",
        "should_deploy=true",
        "should_deploy=false",
    ]


def test_config_requires_env_and_redacts_tokens(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_IDS", [])
    with pytest.raises(RuntimeError):
        config.validate_telegram_config()

    with pytest.raises(ValueError):
        TelegramBot("", ["123"])

    leaked = "400 Client Error for url: https://api.telegram.org/bot123456:ABCdef-99_xyz/sendMessage"
    masked = redact_secrets(leaked, "123456:ABCdef-99_xyz")
    assert "123456:ABCdef-99_xyz" not in masked
    assert "REDACTED_TOKEN" in masked


# ── 7. formatter.py fixes ────────────────────────────────────────────────────


def test_formatter_markdown_and_engine_count():
    msg = format_daily_summary(
        {"price": 3500.0, "change_24h": 0.5},
        [{"title": "Gold [Spot] *rally* _today_ `test`", "link": "https://example.com"}],
    )
    assert "1. [Gold (Spot) rally today test](https://example.com)" in msg
    assert "\\." not in msg

    status = format_manual_status(
        {"price": 3500.0, "change_24h": 0.0},
        pd.Series({"adx": 15.0, "rsi": 50.0}),
        "range",
    )
    assert "۴ موتور" in status
    assert "۵ موتور" not in status

    # Calendar dict formatting in daily summary
    cal_msg = format_daily_summary(
        {"price": 3500.0, "change_24h": -0.3},
        [{"title": "Core PCE", "tehran_date": "2026-11-26", "tehran_time": "17:00", "impact": "High", "forecast": "0.3%"}],
    )
    assert "Core PCE" in cal_msg
    assert "17:00" in cal_msg


# ── 8. risk_guard, lifecycle alerts, news, and backtester ────────────────────


def test_risk_guard_spread_and_high_impact_news_warning():
    now_utc = datetime(2026, 11, 26, 13, 10, tzinfo=timezone.utc)
    news = [
        {
            "title": "CPI m/m",
            "impact": "Medium",
            "date_utc": "2026-11-26T13:15:00Z",
            "tehran_time": "16:45",
        },
        {
            "title": "Core PCE Price Index",
            "impact": "High",
            "date_utc": "2026-11-26T13:30:00Z",
            "tehran_time": "17:00",
        },
    ]
    price = {"price": 3500.0, "bid": 3499.0, "ask": 3501.2, "change_24h": 0.1}
    risk = assess_market_risk(price, news, now_utc=now_utc)
    assert risk["spread"] == 2.2
    assert "اسپرد بالا" in risk["spread_warning"]
    assert "20 دقیقه تا خبر مهم USD" in risk["news_warning"]
    assert risk["nearby_high_news"]["title"] == "Core PCE Price Index"

    sig = TradingSignal(
        direction="BUY",
        entry=3500.0,
        stop_loss=3485.0,
        take_profit=3530.0,
        rr_ratio=2.0,
        win_probability=65.0,
        checks=[Check("Test", True, "ok")],
        confluence=1,
        total_checks=1,
    )
    formatted = format_signal(sig, price, risk_info=risk)
    assert "اسپرد لحظه‌ای" in formatted
    assert "Core PCE Price Index" in formatted


def test_lifecycle_events_1r_tp_sl_and_no_duplicates():
    # First check: bar hits +1R (3515) without hitting TP (3530) -> emits BREAKEVEN_1R once
    idx1 = pd.DatetimeIndex(["2026-11-26 10:05:00"])
    df1 = pd.DataFrame(
        {"open": [3501.0], "high": [3518.0], "low": [3498.0], "close": [3515.0]},
        index=idx1,
    )
    signals = [
        {
            "id": "sig_life_1",
            "timestamp_utc": "2026-11-26T10:04:00Z",
            "direction": "BUY",
            "strategy_name": "اسنایپر پولبک (15M)",
            "entry": 3500.0,
            "stop_loss": 3485.0,
            "take_profit": 3530.0,
            "rr_ratio": 2.0,
            "auto_outcome": "OPEN",
        }
    ]

    evs1 = dashboard_export._evaluate_open_signals(signals, df1)
    assert len(evs1) == 1
    assert evs1[0]["type"] == "BREAKEVEN_1R"
    assert "1R" in format_lifecycle_event(evs1[0])

    # Second check on same bar -> must NOT repeat BREAKEVEN_1R
    evs2 = dashboard_export._evaluate_open_signals(signals, df1)
    assert evs2 == []

    # Third check: later bar hits TP (3530) -> emits TP_HIT once
    idx2 = pd.DatetimeIndex(["2026-11-26 10:05:00", "2026-11-26 10:10:00"])
    df2 = pd.DataFrame(
        {
            "open": [3501.0, 3515.0],
            "high": [3518.0, 3532.0],
            "low": [3498.0, 3514.0],
            "close": [3515.0, 3531.0],
        },
        index=idx2,
    )
    evs3 = dashboard_export._evaluate_open_signals(signals, df2)
    assert len(evs3) == 1
    assert evs3[0]["type"] == "TP_HIT"
    assert "تارگت سیگنال تاچ شد" in format_lifecycle_event(evs3[0])

    # Fourth check: already closed -> no further events
    evs4 = dashboard_export._evaluate_open_signals(signals, df2)
    assert evs4 == []


def test_fetch_news_prefers_economic_calendar(monkeypatch):
    monkeypatch.setattr(
        news_data,
        "get_economic_calendar",
        lambda: [
            {"title": "Past Event", "impact": "High", "is_past": True, "is_today": True},
            {"title": "Upcoming NFP", "impact": "High", "is_past": False, "is_today": True},
        ],
    )
    items = news_data.fetch_news(limit=3)
    assert len(items) == 1
    assert items[0]["title"] == "Upcoming NFP"
    assert items[0]["type"] == "GOLD"


def test_backtester_zero_lookahead_and_trade_simulation():
    # Verify closed HTF slice excludes unclosed 1H bar at 10:20
    idx_1h = pd.date_range("2026-11-20 08:00:00", periods=4, freq="1h")
    df_1h = pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0]}, index=idx_1h)
    sliced = _closed_slice_with_forming_tail(
        df_1h,
        t_eval=pd.Timestamp("2026-11-20 10:20:00"),
        tf_delta=pd.Timedelta(hours=1),
    )
    # 08:00 (closes 09:00) and 09:00 (closes 10:00) are closed; 10:00 (closes 11:00) is NOT!
    assert sliced.index[-2] == pd.Timestamp("2026-11-20 09:00:00")
    assert float(sliced.iloc[-2]["close"]) == 101.0

    # Synthetic 5m steady uptrend during Tehran active hours (06:30+ UTC = 10:00+ Tehran)
    df5m = _make_ohlcv_df(rows=300, start_utc="2026-11-20 07:00:00", freq="5min", base_price=3500.0, step=0.5)

    def simple_buy_strat(s4, s1, s30, s15, s5, live_price):
        if len(s5) < 40:
            return []
        return [
            TradingSignal(
                direction="BUY",
                entry=live_price,
                stop_loss=round(live_price - 5.0, 2),
                take_profit=round(live_price + 10.0, 2),
                rr_ratio=2.0,
                win_probability=65.0,
                strategy_name="Test_Uptrend",
                timeframe="5M",
                candle_ts=str(s5.index[-2]),
            )
        ]

    report = run_backtest(
        df5m=df5m,
        df15m=df5m,
        df30m=df5m,
        df1h=df5m,
        df4h=df5m,
        strategy_fn=simple_buy_strat,
        active_hours_tehran=(10, 24),
        spread_points=0.40,
        min_warmup_4h=205,
    )
    assert report.total_trades >= 1
    assert report.wins >= 1
    assert report.net_r > 0
    summary_text = format_backtest_report(report)
    assert "Test_Uptrend" in summary_text

    # Also verify built-in scan_all_engines runs cleanly in historical backtest mode
    hist_report = run_backtest(
        df5m=df5m,
        df15m=df5m,
        df30m=df5m,
        df1h=df5m,
        df4h=df5m,
        strategy_fn=None,
        active_hours_tehran=(10, 24),
        spread_points=0.40,
        min_warmup_4h=205,
    )
    assert hist_report.total_trades >= 0

    # Verify _is_candle_fresh respects simulated historical now_utc
    from strategies.multi_engine import _is_candle_fresh
    old_ts = pd.Timestamp("2025-01-10 10:00:00")
    assert _is_candle_fresh(old_ts, max_age_minutes=20, now_utc=datetime(2025, 1, 10, 10, 10, tzinfo=timezone.utc)) is True
    assert _is_candle_fresh(old_ts, max_age_minutes=20) is False


def test_sequential_signal_numbering_and_lifecycle_reference(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    hist_path = tmp_path / "dashboard_history.json"
    out_path = tmp_path / "dashboard_data.json"

    monkeypatch.setattr(scan_runner, "load_state", lambda: load_state(str(state_path)))
    monkeypatch.setattr(scan_runner, "save_state", lambda st: save_state(st, str(state_path)))
    monkeypatch.setattr(dashboard_export, "HISTORY_FILE", str(hist_path))
    monkeypatch.setattr(dashboard_export, "OUTPUT_JSON_PATH", out_path)
    monkeypatch.setattr(dashboard_export, "_fetch_economic_news", lambda existing=None: [])
    monkeypatch.setattr(scan_runner, "get_economic_calendar", lambda: [])

    df4h = _make_indicator_df(210, "4h", bullish=True)
    df1h = _make_indicator_df(210, "1h", bullish=True)
    df30 = _make_indicator_df(60, "30min", bullish=True)
    df15 = _make_indicator_df(210, "15min", bullish=True)
    df5 = _make_indicator_df(60, "5min", bullish=True)

    monkeypatch.setattr(scan_runner, "get_gold_4h", lambda: df4h)
    monkeypatch.setattr(scan_runner, "get_gold_1h", lambda: df1h)
    monkeypatch.setattr(scan_runner, "get_gold_30m", lambda: df30)
    monkeypatch.setattr(scan_runner, "get_gold_15m", lambda: df15)
    monkeypatch.setattr(scan_runner, "get_gold_5m", lambda: df5)
    monkeypatch.setattr(scan_runner, "get_gold_price", lambda: {"price": 3600.0, "change_24h": 0.3, "source": "TEST"})
    monkeypatch.setattr(scan_runner, "calculate_indicators", lambda df: df)

    def _make_sig(strat: str, ts: str):
        return TradingSignal(
            direction="BUY",
            entry=3600.0,
            stop_loss=3585.0,
            take_profit=3630.0,
            rr_ratio=2.0,
            win_probability=62.0,
            checks=[Check("Trend", True, "ok")],
            confluence=1,
            total_checks=1,
            timeframe="4H + 1H + 15M",
            strategy_name=strat,
            candle_ts=ts,
        )

    sent_texts = []
    bot = MagicMock(spec=TelegramBot)
    bot.get_main_keyboard.return_value = {}
    bot.get_scan_inline_keyboard.return_value = {}

    def _capture_send(text, **kwargs):
        sent_texts.append(text)
        return True

    bot.send_message.side_effect = _capture_send

    # Signal #1
    monkeypatch.setattr(
        scan_runner,
        "scan_all_engines",
        lambda *a, **kw: ([_make_sig("اسنایپر پولبک (15M)", "2026-11-26 11:45:00")], "صعودی", "ok"),
    )
    scan_runner.run_gold_scan(bot, is_manual=False)
    assert "سیگنال طلا #1 —" in sent_texts[0]
    assert load_state(str(state_path))["last_signal_num"] == 1

    # Failed send must NOT burn #2
    bot.send_message.side_effect = lambda text, **kwargs: False
    monkeypatch.setattr(
        scan_runner,
        "scan_all_engines",
        lambda *a, **kw: ([_make_sig("اسنایپر پولبک (15M)", "2026-11-26 12:00:00")], "صعودی", "ok"),
    )
    scan_runner.run_gold_scan(bot, is_manual=True)
    assert load_state(str(state_path))["last_signal_num"] == 1

    # Signal #2 succeeds (manual so bypasses 120m cooldown cleanly)
    bot.send_message.side_effect = _capture_send
    scan_runner.run_gold_scan(bot, is_manual=True)
    assert "سیگنال طلا #2 —" in sent_texts[1]
    assert load_state(str(state_path))["last_signal_num"] == 2

    exported = json.loads(out_path.read_text(encoding="utf-8"))
    nums = [s["signal_num"] for s in exported["signals"]]
    assert nums == [2, 1]

    # Lifecycle alerts reference exact signal number
    msg_1r = format_lifecycle_event({"type": "BREAKEVEN_1R", "signal": exported["signals"][1]})
    msg_tp = format_lifecycle_event({"type": "TP_HIT", "signal": exported["signals"][0]})
    msg_sl = format_lifecycle_event({"type": "SL_HIT", "signal": exported["signals"][0]})
    assert "سیگنال #1" in msg_1r
    assert "سیگنال #2" in msg_tp
    assert "سیگنال #2" in msg_sl

    # Legacy pre-numbering signal falls back to timestamp instead of #None
    legacy_msg = format_lifecycle_event({
        "type": "BREAKEVEN_1R",
        "signal": {
            "direction": "SELL",
            "strategy_name": "اسکالپ دقیق (5M)",
            "timestamp_tehran": "2026-11-26 13:00",
            "entry": 3560.44,
            "stop_loss": 3566.0,
            "take_profit": 3550.44,
            "rr_ratio": 1.8,
        },
    })
    assert "None" not in legacy_msg
    assert "2026-11-26 13:00" in legacy_msg


