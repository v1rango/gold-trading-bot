"""
Non-blocking market risk & event proximity assessment (advisory warnings only).
Evaluates spread and proximity to High-Impact USD economic releases without
altering strategy entry rules or suppressing demo signals unless explicitly enabled.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def assess_market_risk(
    price: Dict[str, Any],
    news: Optional[List[Dict[str, Any]]] = None,
    now_utc: Optional[datetime] = None,
    news_window_before_min: int = 30,
    news_window_after_min: int = 15,
    max_spread_alert: float = 1.50,
) -> Dict[str, Any]:
    """
    Inspect current bid/ask spread and proximity to High-Impact USD events.
    Returns an advisory dict containing spread, spread_warning, news_warning, and nearby_high_news.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    spread: Optional[float] = None
    spread_warning = ""
    bid = price.get("bid")
    ask = price.get("ask")
    if bid is not None and ask is not None:
        try:
            diff = round(float(ask) - float(bid), 2)
            if diff >= 0:
                spread = diff
                if diff > max_spread_alert:
                    spread_warning = f"⚠️ اسپرد بالا (${diff:.2f} > ${max_spread_alert:.2f})"
        except (TypeError, ValueError):
            pass

    nearby_event: Optional[Dict[str, Any]] = None
    best_abs_min: Optional[float] = None
    news_warning = ""

    for ev in (news or []):
        if str(ev.get("impact", "")).strip() != "High":
            continue
        date_utc = ev.get("date_utc")
        if not date_utc:
            continue
        try:
            ev_dt = datetime.fromisoformat(str(date_utc).replace("Z", "+00:00"))
            if ev_dt.tzinfo is None:
                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        delta_min = (ev_dt - now).total_seconds() / 60.0
        if -news_window_after_min <= delta_min <= news_window_before_min:
            abs_min = abs(delta_min)
            if best_abs_min is None or abs_min < best_abs_min:
                best_abs_min = abs_min
                nearby_event = {
                    "title": ev.get("title", "USD High Impact"),
                    "tehran_time": ev.get("tehran_time", "--:--"),
                    "minutes_until": round(delta_min, 1),
                    "impact": "High",
                }

    if nearby_event is not None:
        mins = nearby_event["minutes_until"]
        t_str = nearby_event["tehran_time"]
        title = nearby_event["title"]
        if mins > 0:
            news_warning = f"⚠️ {int(round(mins))} دقیقه تا خبر مهم USD: {title} ({t_str})"
        else:
            news_warning = f"⚠️ خبر مهم USD ({title} - {t_str}) در جریان/تازه‌منتشر است"

    return {
        "spread": spread,
        "spread_warning": spread_warning,
        "news_warning": news_warning,
        "nearby_high_news": nearby_event,
    }
