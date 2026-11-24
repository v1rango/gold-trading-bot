"""
Telegram message formatter — Gold trading signals (Persian).
"""
from datetime import datetime
import pytz
from strategies.signals import TradingSignal, Check

TEHRAN_TZ = pytz.timezone("Asia/Tehran")


def _now() -> str:
    return datetime.now(TEHRAN_TZ).strftime("%Y/%m/%d  %H:%M")


def _prob_bar(prob: float) -> str:
    """Visual probability bar."""
    filled = round(prob / 10)
    return "█" * filled + "░" * (10 - filled)


def format_signal(sig: TradingSignal, gold_price: dict) -> str:
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

    return (
        f"{dir_emoji} *سیگنال طلا — {dir_text}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت فعلی:   `${gold_price['price']:,.2f}`  {chg_e} `{chg:+.2f}%`\n"
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
        f"⏱ تایم‌فریم: `4H + 1H + 30M`\n"
        f"🕐 `{_now()}`\n"
        f"⚠️ _این سیگنال برای آموزش است، نه توصیه مالی_"
    )


def format_daily_summary(gold: dict, news: list) -> str:
    chg_e = "📈" if gold["change_24h"] >= 0 else "📉"
    news_lines = ""
    for i, n in enumerate(news[:5], 1):
        title = n["title"][:65]
        news_lines += f"  {i}\\. [{title}]({n['link']})\n"
    if not news_lines:
        news_lines = "  اخبار مهمی یافت نشد\n"

    return (
        f"📊 *خلاصه روزانه — طلا*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🥇 *Gold (XAU/USD)*\n"
        f"💰 قیمت: `${gold['price']:,.2f}`\n"
        f"{chg_e} تغییر: `{gold['change_24h']:+.2f}%`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 *اخبار مهم طلا:*\n"
        f"{news_lines}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ ربات ۱۲:۰۰ تا ۰۰:۰۰ فعال — هر ۱۵ دقیقه اسکن\n"
        f"🕐 `{_now()}`"
    )


def format_startup() -> str:
    return (
        "🚀 *ربات طلا فعال شد!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Yahoo Finance: متصل\n"
        "✅ سیستم تحلیل: آماده\n\n"
        "🥇 *دارایی تحت نظر: طلا (XAU/USD)*\n\n"
        "⏰ *ساعت فعالیت:* ۱۲:۰۰ تا ۰۰:۰۰\n"
        "🔄 *اسکن:* هر ۱۵ دقیقه\n\n"
        "🎯 *۸ چک روی ۳ تایم‌فریم:*\n"
        "  • روند 4H — EMA 200\n"
        "  • EMA 20/50 (1H)\n"
        "  • RSI 14 (1H)\n"
        "  • MACD 12,26,9 (1H)\n"
        "  • Bollinger Bands (1H)\n"
        "  • ADX 14 — قدرت روند (1H)\n"
        "  • Stochastic RSI (30M)\n"
        "  • RSI 14 (30M)\n\n"
        "🔒 *فیلترهای کیفیت:*\n"
        "  • حداقل ۵/۸ تأیید\n"
        "  • حداقل R:R = 2.0\n"
        "  • ADX > 20 (بازار ترند)\n\n"
        "⚠️ _سیگنال‌ها برای آموزش هستند_"
    )


def format_no_signal(reason: str = "") -> str | None:
    # Silent — don't spam when no signal
    return None
