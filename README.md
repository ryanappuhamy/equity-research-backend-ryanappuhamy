# Equity Research Platform — Backend (v2)

Single-ticker research engine with portfolio tracking and risk analysis. Collects
objective financial data from multiple sources, analyzes earnings call transcripts,
and generates institutional-style research notes via Claude API.

**Design principle: separation of fact and interpretation.**
- Objective data (prices, reported financials, SEC filings, FRED macro) is collected and stored as-is.
- Real analyst opinions (consensus price targets, rating actions) are passed through with explicit attribution.
- AI-generated interpretation is clearly labeled as such and is constrained to only use numbers present in the input data.

## Architecture

```
main.py               # pipeline entry point (CLI + run_pipeline for API)
config.py             # settings + API keys (from environment)
api.py                # FastAPI server — REST endpoints for reports and portfolio
data_fundamentals.py  # prices (yfinance) + fundamentals (FMP primary, yfinance fallback)
data_sec.py           # SEC EDGAR insider activity (Form 4) — free, official
data_earnings.py      # SEC EDGAR earnings transcript from 8-K EX-99 exhibits
data_macro.py         # FRED macro context — free
peer_comparison.py    # comps table + relative valuation vs peer median
ai_report.py          # Claude API — research notes, transcript analysis, portfolio briefs
portfolio.py          # SQLite portfolio tracker (positions, P&L, weights)
portfolio_risk.py     # risk decomposition, correlation matrix, scenario analysis
```

## Data Sources

| Source | Cost | What it provides |
|--------|------|------------------|
| yfinance | Free | Prices, fallback fundamentals, portfolio live prices |
| Financial Modeling Prep | $14/mo (optional) | Clean fundamentals, peer lists, analyst consensus |
| SEC EDGAR | Free | Insider trading (Form 4), earnings call transcripts (8-K EX-99) |
| FRED | Free (API key) | Macro: rates, CPI, unemployment |
| Anthropic API | Pay per use (~cents) | Research notes, transcript analysis, portfolio briefs |
| SQLite | Free | Local portfolio storage (`portfolio.db`) |

The system works with zero paid keys (yfinance + SEC only), but FMP unlocks
peers, analyst consensus, and cleaner data.

## Setup

```bash
pip install -r requirements.txt
```

Set keys (PowerShell):
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:FMP_API_KEY = "..."        # optional
$env:FRED_API_KEY = "..."       # optional, free from fred.stlouisfed.org
```

## Usage

### CLI — single-ticker research pipeline

```bash
python main.py NVDA
# or with manual peers (no FMP key needed):
python main.py NVDA --peers AMD,AVGO,MRVL,INTC,QCOM
```

Outputs in `output/`:
- `NVDA_report.md` — the research note
- `NVDA_data.json` — all raw data (this is what the frontend consumes)

The pipeline runs seven steps: prices, fundamentals, peer comps, insider activity,
earnings transcript fetch + AI analysis, analyst consensus & macro, and AI report generation.

### API — FastAPI server

```bash
uvicorn api:app --reload
```

Interactive docs at `http://127.0.0.1:8000/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/report/{ticker}` | Run the full single-ticker pipeline and return JSON |
| POST | `/portfolio` | Save a portfolio to the database |
| GET | `/portfolio/analysis` | Risk decomposition for the saved portfolio |
| GET | `/portfolio/brief` | AI weekly brief for all portfolio holdings |

**Example — save a portfolio:**
```bash
curl -X POST http://127.0.0.1:8000/portfolio \
  -H "Content-Type: application/json" \
  -d '{"positions": [{"ticker": "NVDA", "shares": 10, "avg_cost_price": 100.0}]}'
```

**Example — get a report:**
```bash
curl http://127.0.0.1:8000/report/NVDA
```

## Roadmap

- **v1**: single-ticker pipeline, CLI
- **v2 (this)**: earnings transcript analysis, portfolio tracker, risk decomposition, FastAPI wrapper, robust error handling
- **v3**: factor exposure, AI rebalancing recommendations, multi-portfolio support, web frontend integration

## Disclaimer

Educational project. Not financial advice.
