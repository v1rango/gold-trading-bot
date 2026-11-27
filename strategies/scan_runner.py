"""
Shared scan pipeline used by both scan_once.py (GitHub Actions) and main.py (daemon).
"""
from datetime import datetime
import logging
import threading
from typing import Optional

from config import TIMEZONE
from data.gold import (
    get_gold_4h, get_gold_1h, get_gold_30m, get_gold_15m, get_gold_5m, get_gold_price,
)
from strategies.indicators import calculate_indicators
from strategies.multi_engine import (
    scan_all_engines, load_state, save_state, can_send_signal, record_signal, get_htf_bias,
)
from strategies.risk_guard import assess_market_risk
from bot.telegram_bot import TelegramBot
from bot.formatter import (
    format_signal, format_manual_status, format_wakeup_message, format_lifecycle_event,
)
from data.dashboard_export import export_dashboard_snapshot, get_economic_calendar

logger = logging.getLogger("scanner")
_STATE_LOCK = threading.Lock()


def run_gold_scan(
    bot: TelegramBot,
    is_manual: bool = False,
    send_wakeup_msg: bool = False,
    target_chat_id: Optional[str] = None,
    state: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> None:
    """Fetch 4H/1H/30M/15M/5M Spot XAU/USD data, evaluate all engines, and alert Telegram."""
    df4h  = calculate_indicators(get_gold_4h())
    df1h  = calculate_indicators(get_gold_1h())
    df30m = calculate_indicators(get_gold_30m())
    df15m = calculate_indicators(get_gold_15m())
    df5m  = calculate_indicators(get_gold_5m())
    price = get_gold_price()

    htf_dir, htf_text = get_htf_bias(df4h, df1h)
    htf_bias = {"BUY": "BULLISH", "SELL": "BEARISH"}.get(htf_dir, "NEUTRAL")

    try:
        news_items = get_economic_calendar()
    except Exception:
        news_items = []
    risk_info = assess_market_risk(price, news_items)

    candidates, htf_text, reason_1h = scan_all_engines(
        df4h, df1h, df30m, df15m, df5m, live_price=price["price"],
    )

    with _STATE_LOCK:
        if state is None:
            state = load_state()

        if send_wakeup_msg:
            if bot.send_message(
                format_wakeup_message(price, df1h.iloc[-1], htf_bias=htf_text),
                reply_markup=bot.get_main_keyboard(),
                chat_id=target_chat_id,
            ):
                ref_now = now or datetime.now(TIMEZONE)
                state["last_wakeup_date"] = ref_now.strftime("%Y-%m-%d")
                logger.info("Wakeup message sent.")

        sent_any = False
        emitted_signals = []

        for sig in candidates:
            if is_manual:
                allowed, skip_msg = True, ""
            else:
                allowed, skip_msg = can_send_signal(sig, state)

            if not allowed:
                logger.info(f"Skipped {sig.strategy_name} ({sig.direction}): {skip_msg}")
                continue

            next_num = int(state.get("last_signal_num", 0)) + 1
            sig.signal_num = next_num

            logger.info(
                f"Signal triggered: #{next_num} [{sig.strategy_name}] {sig.direction} "
                f"entry={sig.entry} TP={sig.take_profit} SL={sig.stop_loss} RR={sig.rr_ratio}"
            )
            msg = format_signal(sig, price, risk_info=risk_info)
            if bot.send_message(msg, reply_markup=bot.get_scan_inline_keyboard(), chat_id=target_chat_id):
                state["last_signal_num"] = next_num
                if not is_manual:
                    record_signal(sig, state)
                emitted_signals.append(sig)
                sent_any = True
                if is_manual:
                    break

        save_state(state)

        lifecycle_events = []
        try:
            lifecycle_events = export_dashboard_snapshot(
                price=price,
                df4h=df4h,
                df1h=df1h,
                df30m=df30m,
                df15m=df15m,
                df5m=df5m,
                htf_bias=htf_bias,
                htf_text=htf_text,
                reason_1h=reason_1h,
                emitted_signals=emitted_signals,
                risk_info=risk_info,
                news_items=news_items,
            ) or []
        except Exception as e:
            logger.warning(f"Dashboard export warning (non-fatal): {e}")

    for ev in lifecycle_events:
        try:
            bot.send_message(format_lifecycle_event(ev), reply_markup=bot.get_main_keyboard())
        except Exception as e:
            logger.warning(f"Lifecycle alert warning: {e}")

    if not sent_any and is_manual:
        status_msg = format_manual_status(price, df1h.iloc[-1], reason_1h, htf_bias=htf_text)
        bot.send_message(status_msg, reply_markup=bot.get_scan_inline_keyboard(), chat_id=target_chat_id)
        logger.info("Manual scan status sent to Telegram.")
    elif not sent_any:
        logger.info(f"Scan finished silently | {htf_text} | {reason_1h}")
