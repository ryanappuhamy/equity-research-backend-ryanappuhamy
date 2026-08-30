"""
Central configuration.
API keys are read from environment variables — never hardcode them.

AI report generation — pick ONE (see AI_PROVIDER below):
    ANTHROPIC_API_KEY   -> Claude API (best prose; paid — Haiku 4.5 costs cents)
    GEMINI_API_KEY      -> Google Gemini API (Flash tier is free, no card; get a
                           key at https://aistudio.google.com/apikey)
    (neither)           -> structured template reports built from the raw data
Optional:
    ALPHA_VANTAGE_API_KEY -> Alpha Vantage company overview (P/E, revenue growth)
    FMP_API_KEY         -> Financial Modeling Prep (peers, supplementary analyst data)
    FRED_API_KEY        -> FRED macro data (free, register at fred.stlouisfed.org)
    FINNHUB_API_KEY     -> Finnhub analyst consensus, price targets, EPS estimates (free tier)
    DATABASE_URL        -> PostgreSQL connection string (Supabase/Render); falls back to SQLite
    AI_PROVIDER         -> "auto" (default), "anthropic", "gemini", or "none"
    API_SECRET         -> if set, require header  X-API-Key: <value>  on protected routes
    FORCE_PASSWORD     -> required by cache-invalidation / force-regenerate routes
    RATE_LIMIT_DEFAULT -> per-IP limit for all routes (default "120/minute")
    RATE_LIMIT_PIPELINE-> per-IP limit for expensive pipeline routes (default "10/minute")

If ALPHA_VANTAGE_API_KEY is missing, the system falls back to yfinance for fundamentals.
"""

import os

# --- API keys (from environment) ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# --- Security (all opt-in; unset == fully open, e.g. local dev) ---
# API_SECRET: when set, every route except /health and the docs requires
#   header  X-API-Key: <API_SECRET>.  Set it on Render AND on the frontend
#   (NEXT_PUBLIC_API_SECRET) together, or the deployed site breaks.
# FORCE_PASSWORD: gate for the privileged cache-delete / force-regenerate routes
#   (replaces the old hardcoded value). Unset -> those routes are disabled.
API_SECRET = os.environ.get("API_SECRET", "").strip()
FORCE_PASSWORD = os.environ.get("FORCE_PASSWORD", "").strip()

# Per-IP rate limits (slowapi syntax, e.g. "120/minute", "10/minute")
RATE_LIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "120/minute").strip()
RATE_LIMIT_PIPELINE = os.environ.get("RATE_LIMIT_PIPELINE", "10/minute").strip()

# --- AI provider selection ---
# "auto"      -> Anthropic if ANTHROPIC_API_KEY is set, else Gemini if
#                GEMINI_API_KEY is set, else template reports.
# "anthropic" -> force Claude (template fallback if the key is missing).
# "gemini"    -> force Gemini (template fallback if the key is missing).
# "none"      -> always use template reports (no API calls, no cost).
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower()

# --- Claude models (tried in order, newest first) ---
CLAUDE_MODELS = [
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
]

# --- Gemini models (tried in order). Flash tiers are free and more than
# enough for single-user / showcase traffic. ---
GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest",
]


def active_ai_provider() -> str:
    """Resolve which LLM backend to use given AI_PROVIDER and the available keys."""
    if AI_PROVIDER == "anthropic":
        return "anthropic" if ANTHROPIC_API_KEY else "none"
    if AI_PROVIDER == "gemini":
        return "gemini" if GEMINI_API_KEY else "none"
    if AI_PROVIDER == "none":
        return "none"
    # auto
    if ANTHROPIC_API_KEY:
        return "anthropic"
    if GEMINI_API_KEY:
        return "gemini"
    return "none"

# --- Analysis settings ---
PRICE_LOOKBACK_YEARS = 5
PEER_COUNT = 5                  # number of peers in the comps table
RISK_FREE_RATE = 0.04           # used for Sharpe ratio

# --- FRED series used as macro context ---
FRED_SERIES = {
    "fed_funds": "FEDFUNDS",          # Fed funds rate
    "cpi_yoy": "CPIAUCSL",            # CPI (we compute YoY)
    "ten_year": "DGS10",              # 10Y Treasury yield
    "unemployment": "UNRATE",         # Unemployment rate
}

# --- Output ---
OUTPUT_DIR = "output"
PORTFOLIO_DB = os.environ.get("PORTFOLIO_DB", "portfolio.db")


def _normalize_database_url(url: str) -> str:
    """Ensure SQLAlchemy-compatible PostgreSQL driver URL."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_database_url() -> str:
    """PostgreSQL via DATABASE_URL, or local SQLite fallback."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return _normalize_database_url(url)
    return f"sqlite:///{PORTFOLIO_DB}"


DATABASE_URL = get_database_url()
