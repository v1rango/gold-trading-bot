"""
Zero-lookahead backtesting engine for Gold (XAU/USD) strategies.
Supports the built-in multi_engine portfolio as well as custom strategy callables
for side-by-side comparison before promoting strategies to live/demo scanning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple
import math

import pandas as pd

from config import DEDUP_MINUTES, TIMEZONE
from strategies.indicators import calculate_indicators
from strategies.multi_engine import can_send_signal, record_signal, scan_all_engines
from strategies.signals import TradingSignal


TF_DELTAS = {
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
}


@dataclass
class BacktestTrade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str
    strategy_name: str
    timeframe: str
    entry: float
    stop_loss: float
    take_profit: float
    exit_price: float
    outcome: str        # TP | SL | BE | OPEN_END
    pnl_r: float
    pnl_points: float
    tehran_hour: int


@dataclass
class BacktestReport:
    total_trades: int
    wins: int
    losses: int
    breakevens: int
    win_rate: float
    net_r: float
    net_points: float
    gross_profit_r: float
    gross_loss_r: float
    profit_factor: float
    expectancy_r: float
    max_drawdown_r: float
    max_win_streak: int
    max_loss_streak: int
    by_strategy: Dict[str, Dict[str, float]] = field(default_factory=dict)
    by_tehran_hour: Dict[int, Dict[str, float]] = field(default_factory=dict)
    trades: List[BacktestTrade] = field(default_factory=list)


def resample_ohlcv(df_base: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV DataFrame (UTC naive index) to a higher timeframe."""
    df = df_base.sort_index()
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum" if "volume" in df.columns else "count",
    }
    res = df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])
    return res


def _closed_slice_with_forming_tail(
    df_ind: pd.DataFrame,
    t_eval: pd.Timestamp,
    tf_delta: pd.Timedelta,
    lookback: int = 260,
) -> pd.DataFrame:
    """
    Build a strictly lookahead-free slice at evaluation timestamp `t_eval`.
    Closed bars satisfy `bar_open + tf_delta <= t_eval`. Because the strategy engines
    read `iloc[-2]` as the last closed bar and `iloc[-1]` as forming, a trailing
    placeholder row is appended so `iloc[-2]` is always the exact last closed bar.
    """
    closed = df_ind[(df_ind.index + tf_delta) <= t_eval]
    if closed.empty:
        return closed
    tail = closed.tail(lookback)
    placeholder = tail.iloc[[-1]].copy()
    placeholder.index = pd.DatetimeIndex([tail.index[-1] + tf_delta])
    return pd.concat([tail, placeholder])


def _simulate_trade_exit(
    sig: TradingSignal,
    future_bars: pd.DataFrame,
    spread_points: float = 0.0,
    move_to_be_at_1r: bool = False,
) -> Tuple[float, pd.Timestamp, str]:
    """Simulate bar-by-bar exit with pessimistic SL-first ordering inside a bar."""
    half_spread = spread_points / 2.0
    if sig.direction == "BUY":
        fill = sig.entry + half_spread
        risk = max(fill - sig.stop_loss, 1e-6)
        tp = sig.take_profit
        sl = sig.stop_loss
        be_trigger = fill + risk
    else:
        fill = sig.entry - half_spread
        risk = max(sig.stop_loss - fill, 1e-6)
        tp = sig.take_profit
        sl = sig.stop_loss
        be_trigger = fill - risk

    moved_to_be = False
    for ts, bar in future_bars.iterrows():
        hi = float(bar["high"])
        lo = float(bar["low"])
        if sig.direction == "BUY":
            if lo <= sl:
                return sl, ts, ("BE" if moved_to_be else "SL")
            if hi >= tp:
                return tp, ts, "TP"
            if move_to_be_at_1r and not moved_to_be and hi >= be_trigger:
                sl = fill
                moved_to_be = True
        else:
            if hi >= sl:
                return sl, ts, ("BE" if moved_to_be else "SL")
            if lo <= tp:
                return tp, ts, "TP"
            if move_to_be_at_1r and not moved_to_be and lo <= be_trigger:
                sl = fill
                moved_to_be = True

    last_ts = future_bars.index[-1]
    last_close = float(future_bars.iloc[-1]["close"])
    return last_close, last_ts, "OPEN_END"


def _tehran_hour(ts_utc_naive: pd.Timestamp) -> int:
    dt_utc = ts_utc_naive.to_pydatetime().replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(TIMEZONE).hour


def run_backtest(
    df5m: pd.DataFrame,
    df15m: Optional[pd.DataFrame] = None,
    df30m: Optional[pd.DataFrame] = None,
    df1h: Optional[pd.DataFrame] = None,
    df4h: Optional[pd.DataFrame] = None,
    strategy_fn: Optional[Callable[..., List[TradingSignal]]] = None,
    active_hours_tehran: Optional[Tuple[int, int]] = (10, 24),
    spread_points: float = 0.40,
    enforce_cooldown: bool = True,
    single_position_only: bool = True,
    move_to_be_at_1r: bool = False,
    min_warmup_4h: int = 205,
) -> BacktestReport:
    """
    Run a zero-lookahead historical backtest on 5m base bars.
    If `strategy_fn` is None, runs the live `scan_all_engines` portfolio.
    Custom `strategy_fn(s4h, s1h, s30m, s15m, s5m, live_price)` should return List[TradingSignal].
    """
    base_5m = df5m.sort_index()
    if getattr(base_5m.index, "tz", None) is not None:
        base_5m.index = base_5m.index.tz_convert("UTC").tz_localize(None)
    base_5m = base_5m[~base_5m.index.duplicated(keep="last")].dropna()

    d15 = df15m if df15m is not None else resample_ohlcv(base_5m, "15min")
    d30 = df30m if df30m is not None else resample_ohlcv(base_5m, "30min")
    d1h = df1h if df1h is not None else resample_ohlcv(base_5m, "1h")
    d4h = df4h if df4h is not None else resample_ohlcv(base_5m, "4h")

    ind5 = calculate_indicators(base_5m)
    ind15 = calculate_indicators(d15)
    ind30 = calculate_indicators(d30)
    ind1h = calculate_indicators(d1h)
    ind4h = calculate_indicators(d4h)

    state: dict = {"last_dir_utc": {}, "last_engine_bar": {}}
    trades: List[BacktestTrade] = []
    active_until: Optional[pd.Timestamp] = None

    def _default_eval(s4, s1, s30, s15, s5, live_price, now_utc=None):
        cands, _, _ = scan_all_engines(s4, s1, s30, s15, s5, live_price=live_price, now_utc=now_utc)
        return cands

    # Walk closed 5m bars from index 0..len-2 (need at least 1 future bar to simulate exit)
    for i in range(len(ind5) - 1):
        bar_open = ind5.index[i]
        t_eval = bar_open + TF_DELTAS["5m"]
        th = _tehran_hour(t_eval)
        if active_hours_tehran is not None:
            start_h, end_h = active_hours_tehran
            if not (start_h <= th < end_h):
                continue

        if single_position_only and active_until is not None and bar_open <= active_until:
            continue

        s4 = _closed_slice_with_forming_tail(ind4h, t_eval, TF_DELTAS["4h"])
        s1 = _closed_slice_with_forming_tail(ind1h, t_eval, TF_DELTAS["1h"])
        if len(s4) < min_warmup_4h or len(s1) < min_warmup_4h:
            continue

        s30 = _closed_slice_with_forming_tail(ind30, t_eval, TF_DELTAS["30m"])
        s15 = _closed_slice_with_forming_tail(ind15, t_eval, TF_DELTAS["15m"])
        s5 = _closed_slice_with_forming_tail(ind5, t_eval, TF_DELTAS["5m"])
        if len(s30) < 35 or len(s15) < 35 or len(s5) < 35:
            continue

        live_price = float(ind5.iloc[i]["close"])
        now_utc = t_eval.to_pydatetime().replace(tzinfo=timezone.utc)
        candidates = (
            strategy_fn(s4, s1, s30, s15, s5, live_price)
            if strategy_fn is not None
            else _default_eval(s4, s1, s30, s15, s5, live_price, now_utc=now_utc)
        )
        if not candidates:
            continue

        future_bars = ind5.iloc[i + 1 :]
        if future_bars.empty:
            break

        for sig in candidates:
            if enforce_cooldown:
                ok, _ = can_send_signal(sig, state, now_utc=now_utc)
                if not ok:
                    continue

            exit_price, exit_ts, outcome = _simulate_trade_exit(
                sig,
                future_bars,
                spread_points=spread_points,
                move_to_be_at_1r=move_to_be_at_1r,
            )

            half_spread = spread_points / 2.0
            fill = sig.entry + half_spread if sig.direction == "BUY" else sig.entry - half_spread
            risk_pts = max(abs(fill - sig.stop_loss), 1e-6)
            raw_pts = (exit_price - fill) if sig.direction == "BUY" else (fill - exit_price)
            if outcome == "BE":
                raw_pts = 0.0
            pnl_r = raw_pts / risk_pts

            trades.append(
                BacktestTrade(
                    entry_time=t_eval,
                    exit_time=exit_ts,
                    direction=sig.direction,
                    strategy_name=sig.strategy_name,
                    timeframe=sig.timeframe,
                    entry=round(fill, 2),
                    stop_loss=sig.stop_loss,
                    take_profit=sig.take_profit,
                    exit_price=round(exit_price, 2),
                    outcome=outcome,
                    pnl_r=round(pnl_r, 3),
                    pnl_points=round(raw_pts, 2),
                    tehran_hour=th,
                )
            )
            if enforce_cooldown:
                record_signal(sig, state, now_utc=now_utc)
            if single_position_only:
                active_until = exit_ts
                break

    return _summarize_trades(trades)


def _summarize_trades(trades: List[BacktestTrade]) -> BacktestReport:
    wins = sum(1 for t in trades if t.pnl_r > 0)
    losses = sum(1 for t in trades if t.pnl_r < 0)
    bes = sum(1 for t in trades if t.pnl_r == 0)
    decided = wins + losses
    win_rate = (wins / decided) * 100.0 if decided > 0 else 0.0

    gross_profit_r = sum(t.pnl_r for t in trades if t.pnl_r > 0)
    gross_loss_r = abs(sum(t.pnl_r for t in trades if t.pnl_r < 0))
    net_r = gross_profit_r - gross_loss_r
    net_points = sum(t.pnl_points for t in trades)
    pf = gross_profit_r / gross_loss_r if gross_loss_r > 0 else (99.9 if gross_profit_r > 0 else 0.0)
    expectancy_r = net_r / len(trades) if trades else 0.0

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    cur_w = 0
    cur_l = 0
    max_w = 0
    max_l = 0
    by_strat: Dict[str, Dict[str, float]] = {}
    by_hour: Dict[int, Dict[str, float]] = {}

    for t in trades:
        equity += t.pnl_r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

        if t.pnl_r > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        elif t.pnl_r < 0:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
        else:
            cur_w = 0
            cur_l = 0

        s_rec = by_strat.setdefault(t.strategy_name, {"trades": 0, "wins": 0, "losses": 0, "net_r": 0.0})
        s_rec["trades"] += 1
        s_rec["wins"] += 1 if t.pnl_r > 0 else 0
        s_rec["losses"] += 1 if t.pnl_r < 0 else 0
        s_rec["net_r"] = round(s_rec["net_r"] + t.pnl_r, 3)

        h_rec = by_hour.setdefault(t.tehran_hour, {"trades": 0, "wins": 0, "net_r": 0.0})
        h_rec["trades"] += 1
        h_rec["wins"] += 1 if t.pnl_r > 0 else 0
        h_rec["net_r"] = round(h_rec["net_r"] + t.pnl_r, 3)

    return BacktestReport(
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        breakevens=bes,
        win_rate=round(win_rate, 2),
        net_r=round(net_r, 2),
        net_points=round(net_points, 2),
        gross_profit_r=round(gross_profit_r, 2),
        gross_loss_r=round(gross_loss_r, 2),
        profit_factor=round(pf, 2),
        expectancy_r=round(expectancy_r, 3),
        max_drawdown_r=round(max_dd, 2),
        max_win_streak=max_w,
        max_loss_streak=max_l,
        by_strategy=by_strat,
        by_tehran_hour=dict(sorted(by_hour.items())),
        trades=trades,
    )


def format_backtest_report(report: BacktestReport) -> str:
    lines = [
        "=" * 56,
        f"Trades: {report.total_trades} ({report.wins}W / {report.losses}L / {report.breakevens}BE)",
        f"Win Rate: {report.win_rate:.1f}% | Net R: {report.net_r:+.2f}R ({report.net_points:+.2f}$)",
        f"Profit Factor: {report.profit_factor:.2f} | Expectancy: {report.expectancy_r:+.3f}R/trade",
        f"Max Drawdown: -{report.max_drawdown_r:.2f}R | Streaks: +{report.max_win_streak}W / -{report.max_loss_streak}L",
        "-" * 56,
    ]
    for name, info in report.by_strategy.items():
        dec = info["wins"] + info["losses"]
        wr = (info["wins"] / dec * 100.0) if dec > 0 else 0.0
        lines.append(f"  • {name}: {int(info['trades'])} trades | WR {wr:.1f}% | Net {info['net_r']:+.2f}R")
    lines.append("=" * 56)
    return "\n".join(lines)
