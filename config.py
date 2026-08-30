"""
Central configuration.
API keys are read from environment variables — never hardcode them.

AI report generation — free-first fallback chain (see AI_PROVIDER below):
    GEMINI_API_KEY        -> Google Gemini (free, 1M context) — the primary
    OPENAI_COMPAT_API_KEY -> any OpenAI-compatible free endpoint (Groq default;
                             also Cerebras / OpenRouter / Mistral / DeepSeek)
    ANTHROPIC_API_KEY     -> Claude — emergency fallback only (paid)
    (none set)            -> structured template reports built from the raw data
Optional:
    ALPHA_VANTAGE_API_KEY -> Alpha Vantage company overview (P/E, revenue growth)
    FMP_API_KEY         -> Financial Modeling Prep (peers, supplementary analyst data)
    FRED_API_KEY        -> FRED macro data (free, register at fred.stlouisfed.org)
    FINNHUB_API_KEY     -> Finnhub analyst consensus, price targets, EPS estimates (free tier)
    DATABASE_URL        -> PostgreSQL connection string (Supabase/Render); falls back to SQLite
    AI_PROVIDER         -> "auto" (default) | "gemini" | "openai_compat" | "anthropic" | "none"
    OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_MODEL -> point the fallback tier elsewhere
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
# The pipeline tries providers in order, cheapest first, and only advances to the
# next one when a call actually fails (rate limit, error, model gone). Claude is
# the last resort — with free tiers healthy it essentially never runs.
#
#   AI_PROVIDER = "auto" (default)  -> gemini -> openai_compat -> anthropic -> template
#                 "gemini"          -> gemini only
#                 "openai_compat"   -> the OpenAI-compatible endpoint only
#                 "anthropic"       -> Claude only
#                 "none"            -> template reports, no API calls
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").strip().lower()

# --- Claude models (tried in order, newest first). Emergency fallback only. ---
CLAUDE_MODELS = [
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
]

# --- Gemini models (tried in order). Free tier, 1M context — the primary. ---
GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-flash-latest",
]

# --- OpenAI-compatible free fallback ---
# Defaults target Groq (free tier, fast, reliable). Groq / Cerebras / OpenRouter
# / Mistral / DeepSeek all speak this same API — to switch, change base URL +
# model (and key). Leave OPENAI_COMPAT_API_KEY blank to skip this tier entirely.
OPENAI_COMPAT_API_KEY = os.environ.get("OPENAI_COMPAT_API_KEY", "").strip()
OPENAI_COMPAT_BASE_URL = os.environ.get(
    "OPENAI_COMPAT_BASE_URL", "https://api.groq.com/openai/v1"
).strip().rstrip("/")
OPENAI_COMPAT_MODEL = os.environ.get("OPENAI_COMPAT_MODEL", "openai/gpt-oss-120b").strip()


def ai_provider_chain() -> list[str]:
    """Ordered providers to try. Free tiers first, Claude last, [] == template."""
    have = {
        "gemini": bool(GEMINI_API_KEY),
        "openai_compat": bool(OPENAI_COMPAT_API_KEY),
        "anthropic": bool(ANTHROPIC_API_KEY),
    }
    if AI_PROVIDER == "none":
        return []
    if AI_PROVIDER in have:
        return [AI_PROVIDER] if have[AI_PROVIDER] else []
    # auto
    return [name for name in ("gemini", "openai_compat", "anthropic") if have[name]]

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
