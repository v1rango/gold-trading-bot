"""
Telegram message formatter — Gold trading signals (Persian).
"""
from datetime import datetime
import re
import pytz
from strategies.signals import TradingSignal, Check

TEHRAN_TZ = pytz.timezone("Asia/Tehran")


def _clean_md_text(text: str) -> str:
    """Clean Markdown-sensitive characters so Telegram legacy Markdown links parse reliably."""
    cleaned = str(text or "").replace("[", "(").replace("]", ")")
    return re.sub(r"[*_`]", "", cleaned)


def _now() -> str:
    return datetime.now(TEHRAN_TZ).strftime("%Y/%m/%d  %H:%M")


def _prob_bar(prob: float) -> str:
    """Visual probability bar."""
    filled = round(prob / 10)
    return "█" * filled + "░" * (10 - filled)


def format_signal(sig: TradingSignal, gold_price: dict, risk_info: dict | None = None) -> str:
    direction = sig.direction
    is_buy    = direction == "BUY"

    # Header
    dir_emoji = "🟢" if is_buy else "🔴"
    dir_text  = "خرید (LONG)" if is_buy else "فروش (SHORT)"

    # Price levels
    entry = sig.entry
    tp    = sig.take_profit
    sl    = sig.stop_loss

    if is_buy:
        tp_pct = ((tp - entry) / entry) * 100
        sl_pct = ((sl - entry) / entry) * 100
    else:
        tp_pct = ((entry - tp) / entry) * 100
        sl_pct = ((entry - sl) / entry) * 100

    # R:R label
    rr = sig.rr_ratio
    rr_label = ("🔥 عالی" if rr >= 3.0 else
                "✅ خوب"  if rr >= 2.5 else
                "✅ قابل‌قبول")

    # Win probability
    prob     = sig.win_probability
    prob_bar = _prob_bar(prob)
    prob_label = ("💎 بسیار خوب" if prob >= 72 else
                  "✅ خوب"        if prob >= 65 else
                  "⚠️ متوسط")

    # Checks breakdown
    checks_text = ""
    for c in sig.checks:
        icon = "✅" if c.passed else "❌"
        checks_text += f"  {icon} *{c.name}:* {c.detail}\n"

    # 24h price info
    chg = gold_price["change_24h"]
    chg_e = "📈" if chg >= 0 else "📉"
    src = gold_price.get("source", "XAU/USD")

    risk_lines = ""
    if risk_info:
        if risk_info.get("spread") is not None:
            risk_lines += f"📏 اسپرد لحظه‌ای: `${risk_info['spread']:.2f}`\n"
        if risk_info.get("spread_warning"):
            risk_lines += f"{risk_info['spread_warning']}\n"
        if risk_info.get("news_warning"):
            risk_lines += f"{risk_info['news_warning']}\n"

    return (
        f"{dir_emoji} *سیگنال طلا — {dir_text}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت لحظه‌ای: `${gold_price['price']:,.2f}`  {chg_e} `{chg:+.2f}%`\n"
        f"📡 منبع دقیق: `{src}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 نقطه ورود:   `${entry:,.2f}`\n"
        f"{'🟩' if is_buy else '🟥'} حد سود:       `${tp:,.2f}`  `({tp_pct:+.2f}%)`\n"
        f"🛑 حد ضرر:      `${sl:,.2f}`  `({sl_pct:+.2f}%)`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 ریسک به ریوارد:  `1 : {rr:.1f}`  {rr_label}\n"
        f"🎲 احتمال موفقیت:  `{prob:.0f}%`  {prob_label}\n"
        f"    `[{prob_bar}]`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *تأیید استراتژی‌ها ({sig.confluence}/{sig.total_checks}):*\n"
        f"{checks_text}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ استراتژی: `{sig.strategy_name}`\n"
        f"⏱ تایم‌فریم: `{sig.timeframe}`\n"
        f"{risk_lines}"
        f"🕐 `{_now()}`\n"
        f"⚠️ _این سیگنال برای آموزش است، نه توصیه مالی_"
    )


def format_manual_status(gold_price: dict, curr_1h, reason: str, htf_bias: str = "") -> str:
    """Format manual scan market report when no trade signal triggers."""
    src = gold_price.get("source", "XAU/USD")
    bid_ask = ""
    if "bid" in gold_price and "ask" in gold_price:
        bid_ask = f" (Bid: `{gold_price['bid']:,.2f}` | Ask: `{gold_price['ask']:,.2f}`)"
    bias_line = f"🧭 {htf_bias}\n" if htf_bias else ""
    return (
        f"🔍 *گزارش اسکن دستی طلا*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت لحظه‌ای: `${gold_price['price']:,.2f}`{bid_ask}\n"
        f"📡 منبع: `{src}`\n"
        f"{bias_line}"
        f"📊 وضعیت 1H: `{reason}`\n"
        f"📈 شاخص روند (ADX): `{curr_1h['adx']:.1f}` | ⚡ RSI: `{curr_1h['rsi']:.1f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ _در حال رصد ۴ موتور معاملاتی (5M/15M/30M/1H) — فعلاً ستاپ باکیفیت آماده نیست._\n"
        f"🕐 `{_now()}`"
    )


def format_wakeup_message(gold: dict, curr_1h, htf_bias: str = "") -> str:
    """Morning wakeup message at 10:00 AM Tehran."""
    chg = gold["change_24h"]
    chg_e = "📈" if chg >= 0 else "📉"
    src = gold.get("source", "OANDA:XAUUSD")
    bias_line = f"🧭 {htf_bias}\n" if htf_bias else ""
    return (
        f"☀️ *سلام! بیدار شدم — شروع رصد امروز طلا*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت شروع روز: `${gold['price']:,.2f}`  {chg_e} `{chg:+.2f}%`\n"
        f"📡 منبع: `{src}`\n"
        f"{bias_line}"
        f"📈 ADX فعلی: `{curr_1h['adx']:.1f}` | ⚡ RSI: `{curr_1h['rsi']:.1f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 تا ساعت ۰۰:۰۰ بامداد هر ۵ دقیقه بازار رو با موتورهای 5M/15M/30M/1H اسکن می‌کنم.\n"
        f"🕐 `{_now()}`"
    )


def format_sleep_message(gold: dict) -> str:
    """Goodnight message at 00:00 AM Tehran."""
    chg = gold["change_24h"]
    chg_e = "📈" if chg >= 0 else "📉"
    src = gold.get("source", "OANDA:XAUUSD")
    return (
        f"😴 *ساعت ۱۲ شب شد — من می‌رم بخوابم!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 آخرین قیمت طلا: `${gold['price']:,.2f}`  {chg_e} `{chg:+.2f}%`\n"
        f"📡 منبع: `{src}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌙 رصد خودکار تا فردا ساعت ۱۰:۰۰ صبح متوقف می‌شه.\n"
        f"☀️ فردا صبح دوباره بیدار می‌شم. شب بخیر!\n"
        f"🕐 `{_now()}`"
    )


def format_daily_summary(gold: dict, news: list) -> str:
    chg_e = "📈" if gold["change_24h"] >= 0 else "📉"
    news_lines = ""
    for i, n in enumerate(news[:5], 1):
        title = _clean_md_text(str(n.get("title", ""))[:65])
        if n.get("tehran_time"):
            imp = "🔴" if n.get("impact") == "High" else "🟡"
            dt_str = f"{n.get('tehran_date', '')} {n.get('tehran_time', '')}".strip()
            meta = f" | Fc:{n['forecast']}" if n.get("forecast") else ""
            news_lines += f"  {i}. {imp} *{title}* (`{dt_str}`{meta})\n"
        elif n.get("link"):
            news_lines += f"  {i}. [{title}]({n['link']})\n"
        else:
            news_lines += f"  {i}. {title}\n"
    if not news_lines:
        news_lines = "  اخبار مهمی یافت نشد\n"

    return (
        f"📊 *خلاصه روزانه — طلا*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🥇 *Gold (XAU/USD)*\n"
        f"💰 قیمت: `${gold['price']:,.2f}`\n"
        f"{chg_e} تغییر: `{gold['change_24h']:+.2f}%`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 *اخبار و رویدادهای مهم دلار/طلا:*\n"
        f"{news_lines}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ ربات ۱۰:۰۰ تا ۰۰:۰۰ فعال — هر ۵ دقیقه اسکن\n"
        f"🕐 `{_now()}`"
    )


def format_lifecycle_event(ev: dict) -> str:
    """Format TP_HIT / SL_HIT / BREAKEVEN_1R follow-up alerts for previously emitted signals."""
    ev_type = ev.get("type", "")
    sig = ev.get("signal", {})
    direction = sig.get("direction", "")
    dir_fa = "خرید (BUY)" if direction == "BUY" else "فروش (SELL)"
    strat = _clean_md_text(sig.get("strategy_name", ""))
    entry = float(sig.get("entry", 0.0))
    sl = float(sig.get("stop_loss", 0.0))
    tp = float(sig.get("take_profit", 0.0))
    rr = float(sig.get("rr_ratio", 0.0))

    if ev_type == "TP_HIT":
        return (
            f"🎯 *تارگت تاچ شد!* (`{dir_fa}`)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ استراتژی: `{strat}`\n"
            f"🎯 ورود: `${entry:,.2f}` ➔ 🟩 تارگت: `${tp:,.2f}` (`1:{rr:.1f}`)\n"
            f"🕐 `{_now()}`"
        )
    if ev_type == "SL_HIT":
        return (
            f"🛑 *استاپ تاچ شد* (`{dir_fa}`)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ استراتژی: `{strat}`\n"
            f"🎯 ورود: `${entry:,.2f}` ➔ 🛑 استاپ: `${sl:,.2f}`\n"
            f"🕐 `{_now()}`"
        )
    return (
        f"🛡️ *رسیدن به 1R — پیشنهاد ریسک‌فری (BE)* (`{dir_fa}`)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ استراتژی: `{strat}`\n"
        f"🎯 ورود: `${entry:,.2f}` | 🟩 تارگت: `${tp:,.2f}`\n"
        f"💡 قیمت به سود +1R رسید؛ می‌توانید استاپ را روی نقطه ورود بگذارید.\n"
        f"🕐 `{_now()}`"
    )


def format_startup() -> str:
    return (
        "🚀 *ربات پیشرفته طلا (نسخه ۴ تایم‌فریم) فعال شد!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ دیتای زنده Spot (OANDA:XAUUSD): متصل\n"
        "✅ موتورهای تحلیلی: آماده\n\n"
        "🥇 *دارایی تحت نظر: طلا (XAU/USD)*\n\n"
        "⏰ *ساعت فعالیت:* ۱۰:۰۰ صبح تا ۰۰:۰۰ شب\n"
        "🔄 *اسکن:* هر ۵ دقیقه\n\n"
        "🎯 *۴ موتور هم‌راستا با روند کلان 4H+1H:*\n"
        "  • همگرایی جامع (1H) — R:R ≥ 2.0\n"
        "  • پولبک دقیق (30M) — StochRSI / RSI7\n"
        "  • اسنایپر (15M) — BB / Stoch / ۳ کندلی / RSI7\n"
        "  • اسکالپ دقیق (5M) — کنترل دریفت زنده\n\n"
        "🔒 *مدیریت ریسک:*\n"
        "  • کول‌داون ۲ ساعته در هر جهت (ضد تکرار)\n"
        "  • استاپ داینامیک ATR\n\n"
        "⚠️ _سیگنال‌ها برای آموزش هستند_"
    )


def format_no_signal(reason: str = "") -> str | None:
    # Silent — don't spam when no signal
    return None
