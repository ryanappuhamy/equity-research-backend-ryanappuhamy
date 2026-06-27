# Changelog — Equity Research Platform

## 2026-05-21 — Project Conception
- Initial idea for equity research platform
- Stack selection: Python/FastAPI backend + Next.js frontend + Supabase
- Identified SEC EDGAR as key differentiator (free, primary institutional source)

## 2026-06-24 — Backend Foundation
- Built complete FastAPI backend from scratch
- 7-step modular data pipeline:
  1. Price & stats (yfinance)
  2. Fundamentals (yfinance + FMP fallback)
  3. Peer comparison
  4. SEC EDGAR insider activity (Form 4, free)
  5. Earnings call transcripts (8-K EX-99 from SEC EDGAR, free)
  6. Analyst consensus + macro context (Finnhub + FRED)
  7. AI report generation (Claude Sonnet 4.6)
- 9 FastAPI endpoints live and tested
- Portfolio tracker with Supabase Postgres
- Price alert system with threshold logic
- Scenario analysis (market -20%, rates +100bps)
- Risk contribution per position
- Migrated from SQLite to Supabase Postgres (Session Pooler)
- Added CORS middleware for Vercel frontend
- Integrated Finnhub for analyst consensus (free tier)
- Deployed backend to Render

## 2026-06-24 — Frontend Base & Deployment
- Dilan provided base Next.js frontend structure as starting point:
  dark fintech layout, card shapes, sidebar navigation
- Deployed frontend to Vercel
- Negotiated 30% student discount with FMP

## 2026-06-25 — Frontend Wiring
- Wired all 4 screens to live backend, removed all hardcoded demo data:
  Research Report, Portfolio, Weekly Brief, Alerts
- Added add/remove positions form in Portfolio
- Fixed decimal separator (comma/period) in Portfolio form
- Fixed alert trigger logic (was showing "Within threshold" incorrectly)
- Fixed alert check: lightweight price fetch instead of full pipeline
  (response time from minutes to <1 second)

## 2026-06-25 — Data Layer & Caching
- Added Alpha Vantage as primary fundamentals source
- Implemented exponential backoff on yfinance (2s/4s/8s, 3 attempts)
- Added multi-layer Supabase cache:
  - Fundamentals: 24h TTL
  - Price history: 30min TTL
  - Full report: 24h TTL (zero Anthropic cost on repeat lookups)
  - Weekly Brief: 7 days TTL
  - SEC EDGAR insider activity: 24h TTL
  - Finnhub analyst consensus: 24h TTL
  - SEC EDGAR earnings transcript: 7 days TTL
  - FRED macro data: 24h TTL
- Live price injection on cache hits (price always current even from cache)
- Added password-protected cache invalidation (ExtraPls)
- Added DELETE /report/{ticker}/cache endpoint
- Mapped new Alpha Vantage fields: ForwardPE, PEGRatio, EVToEBITDA,
  GrossProfitTTM, OperatingMarginTTM, ProfitMargin, DebtToEquity,
  CurrentRatio, RevenueTTM, EBITDA, 52WeekHigh, 52WeekLow

## 2026-06-25 — UX & Loading Experience
- Added Recent Searches with localStorage (max 6 tickers, clickable chips)
- Added "Did You Know?" finance education cards in loading screen
  (15-20s per card, 3s initial delay, fade animation, hardcoded — zero API cost)
- Added cold-start warning message in loading screen
- Added "Something didn't load correctly? Retry" button with password (ExtraPls)

## 2026-06-25 — Research Report Redesign
- Redesigned from single P/E card to 6 metric cards:
  Price, Valuation, Growth, Profitability, Financial Health, Financials TTM
- Added insider activity table with individual transactions
  (name, role, Buy/Sell badge, amount, date)

## 2026-06-26 — Weekly Brief Redesign
- Redesigned with react-markdown (tables, colored P&L, warning blockquotes)
- Added freshness badge ("Cached X hours ago")
- Added Regenerate button with password protection (ExtraPls)
- Fixed duplicate title

## 2026-06-26 — Portfolio Dashboard
- Added sector allocation donut chart with hover animation (recharts, zero API cost)
- Total portfolio value displayed in center of donut
- Legend with sector name, dollar value, and percentage
- Sector data fetched directly from yfinance when not in fundamentals cache (TTL: 30 days)
- Known ETFs (SPY, QQQ, VTI, SOXX) classified automatically without API call
- Sector strings normalized to title case to avoid duplicates

## 2026-06-26 — Performance vs Benchmark
- Added new backend endpoint `GET /portfolio/performance?benchmark=SPY`
- Fetches daily price history for all positions using single yf.download() call
- Calculates daily NAV, Sharpe ratio, max drawdown, total return
- Benchmark selector: SPY, QQQ, SOXX, VTI — cached separately per benchmark (24h TTL)
- Frontend line chart with period selector: 1D, 7D, 1M, 6M, 1Y, 5Y, MAX (client-side filtering, zero extra API calls)
- Portfolio line in blue, benchmark in muted gray

## 2026-06-26 — Research Report Improvements
- Rendered AI Research Note with react-markdown (same styling as Weekly Brief)
- Fixed insider activity to show individual transactions (name, role, Buy/Sell badge, amount, date)
- Expanded Form 4 parser to include transaction codes A, D, F, M in addition to P and S
- Added PDF download button for research reports (jsPDF, zero API cost)
- Truncated earnings transcript to 8000 characters before passing to Claude (reduces cost ~40%)

## 2026-06-26 — Cost Optimization
- Report cache extended: full report cached 24h (zero Anthropic cost on repeat lookups)
- Sector cache TTL set to 30 days (changes quarterly at most)
- Portfolio performance cache TTL set to 7 days
- Prompt caching considered for future implementation
