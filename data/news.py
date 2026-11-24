import feedparser
import logging

logger = logging.getLogger(__name__)

FEEDS = [
    {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "CoinTelegraph", "url": "https://cointelegraph.com/rss"},
]

BTC_KEYWORDS  = ["bitcoin", "btc", "crypto", "blockchain"]
GOLD_KEYWORDS = ["gold", "xau", "precious", "commodity", "commodities"]


def fetch_news(limit: int = 6) -> list:
    """Fetch latest BTC / Gold news from public RSS feeds."""
    results = []

    for feed_info in FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:15]:
                title   = entry.get("title", "")
                summary = entry.get("summary", "")[:200]
                link    = entry.get("link", "")
                text    = (title + " " + summary).lower()

                is_btc  = any(k in text for k in BTC_KEYWORDS)
                is_gold = any(k in text for k in GOLD_KEYWORDS)

                if is_btc or is_gold:
                    results.append({
                        "title":  title,
                        "source": feed_info["name"],
                        "link":   link,
                        "type":   "BTC" if is_btc else "GOLD",
                    })
        except Exception as e:
            logger.warning(f"News fetch error ({feed_info['name']}): {e}")

    return results[:limit]
