"""
Recent company news from Finnhub, filtered to headlines that name the company.

Finnhub's company_news is noisy (a NVDA query returns Robinhood or Chipotle
pieces), so every caller goes through relevant_news().
"""

import datetime as dt
import re

from fastapi import APIRouter, HTTPException, Request

import config
import data_fundamentals
import market_cache
from ratelimit import limiter

router = APIRouter(prefix="/news", tags=["news"])

NEWS_TTL_SECONDS = 30 * 60
NEWS_DAYS = 14
NEWS_LIMIT = 8
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

_KEYWORDS = {
    "SPY": ["s&p 500", "s&p500", "spy "],
    "QQQ": ["nasdaq", "qqq"],
}


# Name words too common to identify a company on their own
# ("Western Digital", "General Motors"): match the first two words instead.
_GENERIC_FIRST_WORDS = {
    "american", "general", "western", "eastern", "southern", "northern", "united",
    "first", "international", "global", "national", "royal", "new", "the", "bank",
}


def _keywords(ticker: str, name: str | None) -> list[str]:
    if ticker in _KEYWORDS:
        return _KEYWORDS[ticker]
    words = [ticker.lower()]
    parts = [p.strip(",.").lower() for p in (name or "").split()]
    if parts:
        key = " ".join(parts[:2]) if parts[0] in _GENERIC_FIRST_WORDS and len(parts) > 1 else parts[0]
        if len(key) > 2:
            words.append(key)
    return words


def relevant_news(raw: list[dict], ticker: str, name: str | None, limit: int, with_summary: bool = False) -> list[dict]:
    """Keep headlines that mention the ticker or company name; newest first, no duplicates."""
    # Whole-word match, so "GM" doesn't hit "algorithm".
    pattern = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k.strip()) for k in _keywords(ticker.upper(), name)) + r")(?![a-z0-9])")
    seen: set[str] = set()
    out: list[dict] = []
    for n in sorted(raw, key=lambda n: n.get("datetime") or 0, reverse=True):
        headline = (n.get("headline") or "").strip()
        if not headline or headline in seen:
            continue
        if not pattern.search(headline.lower()):
            continue
        seen.add(headline)
        item = {"headline": headline, "source": n.get("source"), "url": n.get("url"), "datetime": n.get("datetime")}
        if with_summary:
            summary = (n.get("summary") or "").strip()
            item["summary"] = summary[:280] or None
        out.append(item)
        if len(out) >= limit:
            break
    return out


def get_ticker_news(ticker: str) -> dict:
    cached = market_cache._get_json_cache(ticker, "news", NEWS_TTL_SECONDS)
    if cached:
        return cached
    client = data_fundamentals._finnhub_client()
    if client is None:
        return {"available": False, "note": "News source not configured", "ticker": ticker, "items": []}
    today = dt.date.today()
    name = None
    try:
        name = (client.company_profile2(symbol=ticker) or {}).get("name")
    except Exception as e:
        print(f"[warn] Finnhub profile failed for {ticker}: {e}")
    raw = client.company_news(ticker, _from=str(today - dt.timedelta(days=NEWS_DAYS)), to=str(today)) or []
    result = {
        "available": True,
        "ticker": ticker,
        "items": relevant_news(raw, ticker, name, NEWS_LIMIT, with_summary=True),
    }
    market_cache._set_json_cache(ticker, "news", result)
    return result


@router.get("/{ticker}")
@limiter.limit(config.RATE_LIMIT_PIPELINE)
def ticker_news(request: Request, ticker: str):
    """Recent news that names the company (last 14 days, cached 30 min)."""
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    try:
        return get_ticker_news(t)
    except Exception as e:
        print(f"[error] API GET /news/{t} failed: {e}")
        return {"available": False, "note": "News is unavailable right now", "ticker": t, "items": []}
