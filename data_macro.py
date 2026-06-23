"""
FRED — macro context (free API key from fred.stlouisfed.org).

Provides the macro backdrop for the report: rates, inflation, unemployment.
Objective official data.
"""

import requests
import config

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def _fred_latest(series_id: str) -> float | None:
    """Latest observation of a FRED series."""
    params = {
        "series_id": series_id,
        "api_key": config.FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 13,  # enough for YoY on monthly series
    }
    r = requests.get(FRED_BASE, params=params, timeout=20)
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", []) if o["value"] != "."]
    if not obs:
        return None
    return float(obs[0]["value"])


def _fred_yoy(series_id: str) -> float | None:
    """Year-over-year % change of a monthly FRED series (e.g. CPI)."""
    params = {
        "series_id": series_id,
        "api_key": config.FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 13,
    }
    r = requests.get(FRED_BASE, params=params, timeout=20)
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", []) if o["value"] != "."]
    if len(obs) < 13:
        return None
    obs.sort(key=lambda o: o["date"])  # ascending, oldest first
    year_ago = float(obs[-13]["value"])
    latest = float(obs[-1]["value"])
    yoy = latest / year_ago - 1
    if yoy > 0.15 or yoy < -0.05:
        print(f"Warning: {series_id} YoY {yoy:.2%} outside expected range, returning None")
        return None
    return yoy


def get_macro_context() -> dict:
    """Macro snapshot for the report. Empty dict if no FRED key set."""
    if not config.FRED_API_KEY:
        return {"available": False, "note": "Set FRED_API_KEY for macro context (free)"}

    try:
        return {
            "available": True,
            "fed_funds_rate": _fred_latest(config.FRED_SERIES["fed_funds"]),
            "ten_year_yield": _fred_latest(config.FRED_SERIES["ten_year"]),
            "cpi_yoy": round(_fred_yoy(config.FRED_SERIES["cpi_yoy"]) or 0, 4),
            "unemployment_rate": _fred_latest(config.FRED_SERIES["unemployment"]),
        }
    except Exception as e:
        return {"available": False, "note": f"FRED error: {e}"}
