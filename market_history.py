"""
Long monthly price history for the PAC (savings plan) simulator.
"""

import re

from fastapi import APIRouter, HTTPException, Query, Request

import config
import market_cache
from ratelimit import limiter
from yfinance_client import yf_download

router = APIRouter(prefix="/market", tags=["market"])

MONTHLY_TTL_SECONDS = 24 * 3600
MONTHLY_YEARS = 15
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def get_monthly_closes(ticker: str) -> dict:
    cached = market_cache._get_json_cache(ticker, "monthly", MONTHLY_TTL_SECONDS)
    if cached:
        return cached
    data = yf_download(ticker, period=f"{MONTHLY_YEARS}y", interval="1mo", auto_adjust=True, progress=False)
    if data is None or data.empty:
        return {"available": False, "note": f"No price history for {ticker}", "ticker": ticker, "points": []}
    close = data["Close"]
    if hasattr(close, "columns"):  # yfinance may return a one-column frame
        close = close.iloc[:, 0]
    points = [{"month": idx.strftime("%Y-%m"), "close": round(float(v), 4)} for idx, v in close.dropna().items()]
    result = {"available": True, "ticker": ticker, "points": points}
    market_cache._set_json_cache(ticker, "monthly", result)
    return result


@router.get("/monthly")
@limiter.limit(config.RATE_LIMIT_PIPELINE)
def monthly(request: Request, ticker: str = Query(...)):
    """Monthly adjusted closes for the last 15 years (cached 1 day)."""
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    try:
        return get_monthly_closes(t)
    except Exception as e:
        print(f"[error] API GET /market/monthly failed for {t}: {e}")
        return {"available": False, "note": str(e), "ticker": t, "points": []}
