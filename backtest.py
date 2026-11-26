"""
CLI Backtester for XAU/USD strategies (does not affect live scanning or state.json).
Usage:
  python backtest.py --bars 2000
  python backtest.py --csv path/to/xauusd_5m.csv --be-at-1r
"""
from __future__ import annotations

import argparse
import pandas as pd

from data.gold import get_gold_5m, get_gold_15m, get_gold_30m, get_gold_1h, get_gold_4h
from strategies.backtester import format_backtest_report, run_backtest


def main() -> None:
    parser = argparse.ArgumentParser(description="Gold Strategy Backtester")
    parser.add_argument("--csv", type=str, default="", help="Optional CSV with timestamp,open,high,low,close[,volume]")
    parser.add_argument("--bars", type=int, default=1500, help="Bars to fetch from TradingView when --csv is omitted")
    parser.add_argument("--spread", type=float, default=0.40, help="Assumed spread in USD/oz (default 0.40)")
    parser.add_argument("--be-at-1r", action="store_true", help="Simulate moving SL to breakeven at +1R")
    parser.add_argument("--all-hours", action="store_true", help="Test 24h instead of 10:00-24:00 Tehran")
    args = parser.parse_args()

    hours = None if args.all_hours else (10, 24)

    if args.csv:
        df5m = pd.read_csv(args.csv)
        ts_col = "timestamp" if "timestamp" in df5m.columns else df5m.columns[0]
        df5m[ts_col] = pd.to_datetime(df5m[ts_col])
        df5m = df5m.set_index(ts_col).sort_index()
        report = run_backtest(
            df5m=df5m,
            active_hours_tehran=hours,
            spread_points=args.spread,
            move_to_be_at_1r=args.be_at_1r,
        )
    else:
        print(f"Fetching live historical bars (up to {args.bars}) from TradingView...")
        df5m = get_gold_5m(limit=args.bars)
        df15m = get_gold_15m(limit=args.bars)
        df30m = get_gold_30m(limit=args.bars)
        df1h = get_gold_1h(limit=max(args.bars, 400))
        df4h = get_gold_4h(limit=400)
        report = run_backtest(
            df5m=df5m,
            df15m=df15m,
            df30m=df30m,
            df1h=df1h,
            df4h=df4h,
            active_hours_tehran=hours,
            spread_points=args.spread,
            move_to_be_at_1r=args.be_at_1r,
        )

    print(format_backtest_report(report))


if __name__ == "__main__":
    main()
