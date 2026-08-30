"""
Shared yfinance access with retry and exponential backoff.

Rate limits on popular tickers are common; every yfinance call in this
project should go through these helpers (3 attempts, 2s / 4s / 8s delays).
"""

import time
from typing import Callable, TypeVar

import pandas as pd
import yfinance as yf

RETRY_DELAYS_SEC = (2, 4, 8)
MAX_ATTEMPTS = 3

T = TypeVar("T")


def yf_call(fn: Callable[[], T]) -> T:
    """Run a yfinance callable with up to MAX_ATTEMPTS and backoff between failures."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS - 1:
                delay = RETRY_DELAYS_SEC[attempt]
                print(
                    f"[warn] yfinance attempt {attempt + 1}/{MAX_ATTEMPTS} failed: {exc}; "
                    f"retrying in {delay}s"
                )
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def yf_download(*args, **kwargs) -> pd.DataFrame:
    return yf_call(lambda: yf.download(*args, **kwargs))


def yf_ticker_info(ticker: str) -> dict:
    return yf_call(lambda: yf.Ticker(ticker).info or {})


def yf_analyst_price_targets(ticker: str) -> dict | None:
    return yf_call(lambda: yf.Ticker(ticker.upper()).analyst_price_targets)


def yf_last_price(ticker: str) -> float:
    return float(yf_call(lambda: yf.Ticker(ticker.upper()).fast_info.last_price))


def yf_financial_facts(ticker: str) -> dict:
    """
    TTM levels + YoY changes from the annual statements, plus forward revenue
    growth. Every key is optional; returns {} if yfinance is unreachable.
    Keys: revenue_ttm, revenue_yoy, ebitda_ttm, ebitda_yoy, net_income_ttm,
          net_income_yoy, free_cash_flow, revenue_forward.
    """

    def _level_and_yoy(df, *names):
        if df is None or getattr(df, "empty", True):
            return None, None
        for name in names:
            if name in df.index:
                vals = df.loc[name].dropna()
                if len(vals) >= 2 and float(vals.iloc[1]) != 0:
                    cur, prev = float(vals.iloc[0]), float(vals.iloc[1])
                    return cur, round(cur / prev - 1, 4)
                if len(vals) >= 1:
                    return float(vals.iloc[0]), None
        return None, None

    def _fetch() -> dict:
        t = yf.Ticker(ticker.upper())
        out: dict = {}

        try:
            fin = t.financials
            rev, rev_yoy = _level_and_yoy(fin, "Total Revenue", "TotalRevenue")
            ebitda, ebitda_yoy = _level_and_yoy(fin, "EBITDA", "Normalized EBITDA")
            ni, ni_yoy = _level_and_yoy(
                fin, "Net Income", "Net Income Common Stockholders", "NetIncome"
            )
            for key, val in (
                ("revenue_ttm", rev), ("revenue_yoy", rev_yoy),
                ("ebitda_ttm", ebitda), ("ebitda_yoy", ebitda_yoy),
                ("net_income_ttm", ni), ("net_income_yoy", ni_yoy),
            ):
                if val is not None:
                    out[key] = val
        except Exception as e:
            print(f"[warn] yfinance financials for {ticker}: {e}")

        try:
            fcf, _ = _level_and_yoy(t.cashflow, "Free Cash Flow", "FreeCashFlow")
            if fcf is not None:
                out["free_cash_flow"] = fcf
        except Exception as e:
            print(f"[warn] yfinance cashflow for {ticker}: {e}")

        try:
            re = t.revenue_estimate
            if re is not None and not re.empty and "+1y" in re.index and "growth" in re.columns:
                g = re.loc["+1y", "growth"]
                if pd.notna(g):
                    out["revenue_forward"] = round(float(g), 4)
        except Exception as e:
            print(f"[warn] yfinance revenue_estimate for {ticker}: {e}")

        return out

    try:
        return yf_call(_fetch)
    except Exception as e:
        print(f"[error] yfinance financial facts failed for {ticker}: {e}")
        return {}


def yf_ticker_sector(ticker: str) -> str | None:
    """Sector from yfinance fast_info, falling back to info."""

    def _fetch() -> str | None:
        t = yf.Ticker(ticker.upper())
        sector = None
        try:
            fast = t.fast_info
            if hasattr(fast, "get"):
                sector = fast.get("sector")
            else:
                sector = getattr(fast, "sector", None)
        except Exception:
            pass
        if not sector:
            sector = (t.info or {}).get("sector")
        return sector if sector else None

    return yf_call(_fetch)
