# Equity Research Platform — Backend (v1)

Single-ticker research engine: collects objective financial data from multiple
sources and generates an institutional-style research note via Claude API.

**Design principle: separation of fact and interpretation.**
- Objective data (prices, reported financials, SEC filings, FRED macro) is collected and stored as-is.
- Real analyst opinions (consensus price targets, rating actions) are passed through with explicit attribution.
- AI-generated interpretation is clearly labeled as such and is constrained to only use numbers present in the input data.

## Architecture

```
main.py               # pipeline entry point
config.py             # settings + API keys (from environment)
data_fundamentals.py  # prices (yfinance) + fundamentals (FMP primary, yfinance fallback)
data_sec.py           # SEC EDGAR insider activity (Form 4) — free, official
data_macro.py         # FRED macro context — free
peer_comparison.py    # comps table + relative valuation vs peer median
ai_report.py          # Claude API research note generation
```

## Data Sources

| Source | Cost | What it provides |
|--------|------|------------------|
| yfinance | Free | Prices, fallback fundamentals |
| Financial Modeling Prep | $14/mo (optional) | Clean fundamentals, peer lists, analyst consensus |
| SEC EDGAR | Free | Insider trading filings (Form 4) — official |
| FRED | Free (API key) | Macro: rates, CPI, unemployment |
| Anthropic API | Pay per use (~cents) | Report generation |

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

```bash
python main.py NVDA
# or with manual peers (no FMP key needed):
python main.py NVDA --peers AMD,AVGO,MRVL,INTC,QCOM
```

Outputs in `output/`:
- `NVDA_report.md` — the research note
- `NVDA_data.json` — all raw data (this is what the frontend consumes)

## Roadmap

- **v1 (this)**: single-ticker pipeline, CLI
- **v1.5**: FastAPI wrapper exposing `/report/{ticker}` for the web frontend
- **v2**: portfolio layer — factor exposure, correlation matrix, risk decomposition, AI rebalancing notes

## Disclaimer

Educational project. Not financial advice.
