"""
Shared scan pipeline used by both scan_once.py (GitHub Actions) and main.py (daemon).
"""
import logging
from typing import Optional

from data.gold import (
    get_gold_4h, get_gold_1h, get_gold_30m, get_gold_15m, get_gold_5m, get_gold_price,
)
from strategies.indicators import calculate_indicators
from strategies.multi_engine import (
    scan_all_engines, load_state, save_state, can_send_signal, record_signal, get_htf_bias,
)
from bot.telegram_bot import TelegramBot
from bot.formatter import format_signal, format_manual_status, format_wakeup_message
from data.dashboard_export import export_dashboard_snapshot

logger = logging.getLogger("scanner")


def run_gold_scan(
    bot: TelegramBot,
    is_manual: bool = False,
    send_wakeup_msg: bool = False,
    target_chat_id: Optional[str] = None,
    state: Optional[dict] = None,
) -> None:
    """Fetch 4H/1H/30M/15M/5M Spot XAU/USD data, evaluate all engines, and alert Telegram."""
    df4h  = calculate_indicators(get_gold_4h())
    df1h  = calculate_indicators(get_gold_1h())
    df30m = calculate_indicators(get_gold_30m())
    df15m = calculate_indicators(get_gold_15m())
    df5m  = calculate_indicators(get_gold_5m())
    price = get_gold_price()

    _, htf_bias = get_htf_bias(df4h, df1h)

    if send_wakeup_msg:
        bot.send_message(
            format_wakeup_message(price, df1h.iloc[-1], htf_bias=htf_bias),
            reply_markup=bot.get_main_keyboard(),
            chat_id=target_chat_id,
        )
        logger.info("Wakeup message sent.")

    candidates, htf_text, reason_1h = scan_all_engines(
        df4h, df1h, df30m, df15m, df5m, live_price=price["price"],
    )

    if state is None:
        state = load_state()
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

        logger.info(
            f"Signal triggered: [{sig.strategy_name}] {sig.direction} "
            f"entry={sig.entry} TP={sig.take_profit} SL={sig.stop_loss} RR={sig.rr_ratio}"
        )
        msg = format_signal(sig, price)
        if bot.send_message(msg, reply_markup=bot.get_scan_inline_keyboard(), chat_id=target_chat_id):
            if not is_manual:
                record_signal(sig, state)
            emitted_signals.append(sig)
            sent_any = True
            if is_manual:
                break

    save_state(state)

    try:
        export_dashboard_snapshot(
            price=price,
            df4h=df4h,
            df1h=df1h,
            df15m=df15m,
            df5m=df5m,
            htf_bias=htf_bias,
            htf_text=htf_text,
            reason_1h=reason_1h,
            emitted_signals=emitted_signals,
        )
    except Exception as e:
        logger.warning(f"Dashboard export warning (non-fatal): {e}")

    if not sent_any and is_manual:
        status_msg = format_manual_status(price, df1h.iloc[-1], reason_1h, htf_bias=htf_text)
        bot.send_message(status_msg, reply_markup=bot.get_scan_inline_keyboard(), chat_id=target_chat_id)
        logger.info("Manual scan status sent to Telegram.")
    elif not sent_any:
        logger.info(f"Scan finished silently | {htf_text} | {reason_1h}")
