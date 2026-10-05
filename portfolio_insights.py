"""
Per-holding context for the Portfolio page: today's move, 52-week range,
valuation, analyst consensus, next earnings, filtered news and a 1-month
sparkline. Finnhub first (IP-independent, works from Render); yfinance only
for analyst price targets and the S&P 500 P/E, which Finnhub's free tier lacks.
"""

import datetime as dt

from fastapi import APIRouter, Request

import config
import data_fundamentals
import market_cache
import portfolio
from ratelimit import limiter
from ticker_news import relevant_news
from yfinance_client import yf_analyst_price_targets, yf_ticker_info

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

INSIGHTS_TTL_SECONDS = 15 * 60
INDEX_PE_TTL_SECONDS = 24 * 3600
SPARK_DAYS = 22

def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _ticker_insights(client, ticker: str) -> dict:
    out: dict = {"ticker": ticker}
    today = dt.date.today()

    try:
        q = client.quote(ticker) or {}
        out["price"] = _num(q.get("c"))
        out["prev_close"] = _num(q.get("pc"))
        out["change_pct"] = _num(q.get("dp"))
    except Exception as e:
        print(f"[warn] Finnhub quote failed for {ticker}: {e}")

    profile = {}
    try:
        profile = client.company_profile2(symbol=ticker) or {}
    except Exception as e:
        print(f"[warn] Finnhub profile failed for {ticker}: {e}")
    out["name"] = profile.get("name")
    out["logo"] = profile.get("logo") or None

    try:
        m = (client.company_basic_financials(ticker, "all") or {}).get("metric") or {}
        out["high_52w"] = _num(m.get("52WeekHigh"))
        out["low_52w"] = _num(m.get("52WeekLow"))
        out["pe"] = _num(m.get("peTTM")) or _num(m.get("peBasicExclExtraTTM"))
        out["forward_pe"] = _num(m.get("forwardPE"))
        dy = _num(m.get("currentDividendYieldTTM")) or _num(m.get("dividendYieldIndicatedAnnual"))
        out["dividend_yield"] = round(dy / 100, 5) if dy is not None else None
    except Exception as e:
        print(f"[warn] Finnhub metrics failed for {ticker}: {e}")

    try:
        trends = client.recommendation_trends(ticker) or []
        if trends:
            t = trends[0]
            out["analysts"] = {k: int(t.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    except Exception as e:
        print(f"[warn] Finnhub recommendations failed for {ticker}: {e}")

    try:
        cal = client.earnings_calendar(
            _from=str(today), to=str(today + dt.timedelta(days=150)), symbol=ticker
        ).get("earningsCalendar") or []
        if cal:
            nxt = sorted(cal, key=lambda e: e.get("date") or "")[0]
            out["next_earnings"] = {"date": nxt.get("date"), "hour": nxt.get("hour") or None}
    except Exception as e:
        print(f"[warn] Finnhub earnings calendar failed for {ticker}: {e}")

    try:
        raw = client.company_news(ticker, _from=str(today - dt.timedelta(days=6)), to=str(today)) or []
        out["news"] = relevant_news(raw, ticker, out.get("name"), 3)
    except Exception as e:
        print(f"[warn] Finnhub news failed for {ticker}: {e}")
        out["news"] = []

    try:
        targets = yf_analyst_price_targets(ticker) or {}
        out["target_mean"] = _num(targets.get("mean"))
    except Exception as e:
        print(f"[warn] yfinance price targets failed for {ticker}: {e}")

    try:
        hist = data_fundamentals.get_price_history(ticker)
        if not hist.empty and "Close" in hist.columns:
            closes = hist["Close"].dropna().tail(SPARK_DAYS)
            out["spark"] = [round(float(v), 4) for v in closes]
    except Exception as e:
        print(f"[warn] sparkline history failed for {ticker}: {e}")

    return out


def _index_pe() -> float | None:
    cached = market_cache._get_json_cache("SPY", "index_pe", INDEX_PE_TTL_SECONDS)
    if cached:
        return cached.get("pe")
    try:
        pe = _num((yf_ticker_info("SPY") or {}).get("trailingPE"))
    except Exception as e:
        print(f"[warn] S&P 500 P/E unavailable: {e}")
        return None
    if pe:
        market_cache._set_json_cache("SPY", "index_pe", {"pe": pe})
    return pe


def get_portfolio_insights() -> dict:
    tickers = [h["ticker"].upper() for h in portfolio.get_portfolio()]
    if not tickers:
        return {"available": False, "note": "No portfolio saved", "holdings": []}

    client = data_fundamentals._finnhub_client()
    holdings = []
    for ticker in tickers:
        cached = market_cache._get_json_cache(ticker, "insights", INSIGHTS_TTL_SECONDS)
        if cached:
            holdings.append(cached)
            continue
        if client is None:
            holdings.append({"ticker": ticker})
            continue
        data = _ticker_insights(client, ticker)
        market_cache._set_json_cache(ticker, "insights", data)
        holdings.append(data)

    return {
        "available": True,
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
        "index_pe": _index_pe(),
        "holdings": holdings,
    }


@router.get("/insights")
@limiter.limit(config.RATE_LIMIT_PIPELINE)
def portfolio_insights(request: Request):
    """Per-holding market context for the Portfolio page (cached 15 min per ticker)."""
    try:
        return get_portfolio_insights()
    except Exception as e:
        print(f"[error] API GET /portfolio/insights failed: {e}")
        return {"available": False, "note": str(e), "holdings": []}
