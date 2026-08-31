# NEXT — what's left to do

For the history of what's *done*, see `CHANGELOG.md`. This file is only the open items.

## Resuming (any machine, any chat)

1. `git pull` in both `backend/` and `frontend/`.
2. Make sure `backend/.env` and `frontend/.env.local` exist (they're gitignored — Ryan has copies).
3. `cd backend && python -m venv venv && venv\Scripts\python -m pip install -r requirements.txt`
4. `cd frontend && npm install`
5. Run: `backend\start-local.ps1`  and  `cd frontend && npm run dev`  →  :8000 / :3000
6. Tell Claude: "read NEXT.md and the top of CHANGELOG.md".

If Supabase is paused (free tier sleeps after ~1 week idle), resume it from the dashboard — the connection string is unchanged.

## Open items

- [ ] **Supabase RLS** — verify every table has row-level security with service_role policies. Deferred; Ryan's call on priority.
- [ ] **Sector "Unknown" bug** — NVDA + AAPL sometimes resolve to "Unknown" instead of "Technology" in the portfolio sector donut. Inconsistent lookup in `portfolio.get_fundamentals_sectors` / `yfinance_client.yf_ticker_sector` (MU resolves fine, others don't).
- [ ] **Risk contribution: AAPL shows 0%** — should be small but non-zero. Check `portfolio_risk.analyze_portfolio_risk`.
- [ ] **`/dev` diagnostics tab** — password-gated page: live provider health probe, config view, cache stats, optional API call-count history. ~2-3h for the light version. Spec in Claude's memory (`equity-research-todo-dev-tab`).

## Known limitations (not bugs — need money or scope)

- FMP key is dead (old `/api/v3/` endpoints retired). Peers, price targets, rating actions are empty until a paid FMP plan + endpoint rewrite.
- Finnhub free tier: EPS estimates 403 (basic financials + consensus work).
- Non-US tickers: no FX conversion, prices show in local currency.

## Production checklist (Render / Vercel)

Env vars that must be set for full prod functionality:
- Render: `DATABASE_URL`, `GEMINI_API_KEY`, `OPENAI_COMPAT_API_KEY`, `ANTHROPIC_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY`, `FINNHUB_API_KEY`, `API_SECRET`, `FORCE_PASSWORD`
- Vercel: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_API_SECRET` (= Render's `API_SECRET`), `NEXT_PUBLIC_FORCE_PASSWORD` (= Render's `FORCE_PASSWORD`)
- `API_SECRET` / `NEXT_PUBLIC_API_SECRET` must be identical; same for the FORCE_PASSWORD pair.
