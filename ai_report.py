"""
AI research report generation.

IMPORTANT DESIGN PRINCIPLE — separation of fact and interpretation:
  - Everything fed INTO the model is objective data collected upstream.
  - The model's output is clearly labeled as AI-GENERATED INTERPRETATION.
  - Analyst consensus (if present) is REAL analyst opinion, passed through.

The report never invents numbers: the prompt instructs the model to only
reference figures present in the input data.

PROVIDER-AGNOSTIC:
  All model calls go through _llm_complete(), which walks config.ai_provider_chain()
  — free tiers first (Gemini, then an OpenAI-compatible endpoint), Claude only as a
  last resort — advancing to the next provider only when a call actually fails.
  With no key configured, every entry point degrades to a structured template
  built from the collected data — the API never hard-fails.
"""

import json

import requests

import config

# Gemini is called over plain REST (no extra SDK dependency — `requests` is
# already required for the data layer). Auth via the x-goog-api-key header so
# the key never lands in a URL / query string.
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
LLM_TIMEOUT_SECONDS = 120

SYSTEM_PROMPT = """You are an equity research analyst writing an institutional-style research note.

STRICT RULES:
- Use ONLY the numbers provided in the data. Never invent or estimate figures.
- Clearly separate FACTS (the data given) from INTERPRETATION (your analysis).
- When analyst consensus data is provided, attribute it explicitly to analysts, not to yourself.
- If a data point is missing, say so rather than guessing.
- Be balanced: every thesis must include both a bull case and a bear case.
- No hedging filler. Direct, professional language.
"""

REPORT_TEMPLATE = """Generate a one-page equity research note with these sections:

## Company Snapshot
2-3 sentences: what the company does, sector, market cap context.

## Valuation
Where the stock trades vs peers (use the relative valuation data).
State explicitly whether the multiples imply premium or discount and on which metrics.

## Fundamentals Assessment
Margins, returns on capital, growth, balance sheet — what the numbers say.

## Analyst Consensus (if available)
Real analyst data: buy/hold/sell counts, overall recommendation, price targets (mean/high/low),
and next-quarter EPS estimates. Attribute clearly to analysts — cite Finnhub/FMP sources from the data.
Compare current price to analyst price target where both are present.

## Earnings Estimates (if available)
Next quarter EPS estimate and analyst count. Attribute to Finnhub analyst estimates.

## Macro Context (if available)
How the current rate/inflation environment matters for this name.

## Bull Case / Bear Case
3 points each, grounded in the data provided.

## Bottom Line
2-3 sentences. What an investor should focus on. Do NOT give a buy/sell recommendation —
state what the data supports and what the key uncertainties are.

DATA:
{data_json}
"""


# --------------------------------------------------------------------------- #
# Provider dispatch
# --------------------------------------------------------------------------- #
_PROVIDER_FUNCS = {}  # populated below (after the _complete_* defs)


def _llm_complete(system: str, prompt: str, max_tokens: int = 2000) -> tuple[str | None, str | None]:
    """
    Run one completion, walking the provider chain until one succeeds.

    Returns (text, model_label). If every provider fails / none is configured,
    returns (None, None) so callers fall back to their template output.
    """
    chain = config.ai_provider_chain()
    if not chain:
        print("[error] LLM: no provider configured — using template output")
        return None, None

    for provider in chain:
        text, model = _PROVIDER_FUNCS[provider](system, prompt, max_tokens)
        if text:
            return text, model
        print(f"[warn] LLM provider '{provider}' failed — trying next in chain")
    print("[error] LLM: all providers in the chain failed — using template output")
    return None, None


def _complete_anthropic(system: str, prompt: str, max_tokens: int) -> tuple[str | None, str | None]:
    try:
        import anthropic
    except ImportError as e:
        print(f"[error] Anthropic SDK not installed: {e}")
        return None, None

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except Exception as e:
        print(f"[error] Anthropic client init failed: {e}")
        return None, None

    for model in config.CLAUDE_MODELS:
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
            if text:
                return text, model
            print(f"[error] Claude API {model}: empty response")
        except Exception as e:
            print(f"[error] Claude API failed with model {model}: {e}")
            continue
    print("[error] Claude API: all models failed")
    return None, None


def _complete_gemini(system: str, prompt: str, max_tokens: int) -> tuple[str | None, str | None]:
    headers = {"x-goog-api-key": config.GEMINI_API_KEY}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # Gemini 3.x spends part of the output budget on internal reasoning, so
        # give generous headroom (output is free on the flash tier anyway).
        "generationConfig": {
            "maxOutputTokens": max(max_tokens * 2, 4096),
            "temperature": 0.7,
        },
    }

    for model in config.GEMINI_MODELS:
        try:
            resp = requests.post(
                GEMINI_ENDPOINT.format(model=model),
                headers=headers,
                json=body,
                timeout=LLM_TIMEOUT_SECONDS,
            )
            if resp.status_code != 200:
                print(f"[error] Gemini API {model} -> HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            candidates = resp.json().get("candidates") or []
            if not candidates:
                print(f"[error] Gemini API {model}: no candidates returned")
                continue

            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text, model

            finish = candidates[0].get("finishReason")
            print(f"[error] Gemini API {model}: empty text (finishReason={finish})")
        except Exception as e:
            print(f"[error] Gemini API {model} failed: {e}")
            continue
    print("[error] Gemini API: all models failed")
    return None, None


def _complete_openai_compat(system: str, prompt: str, max_tokens: int) -> tuple[str | None, str | None]:
    """Groq / Cerebras / OpenRouter / Mistral / DeepSeek — all the same wire format."""
    if not config.OPENAI_COMPAT_API_KEY:
        return None, None
    model = config.OPENAI_COMPAT_MODEL
    try:
        resp = requests.post(
            f"{config.OPENAI_COMPAT_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.OPENAI_COMPAT_API_KEY}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=LLM_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            print(f"[error] OpenAI-compat {model} -> HTTP {resp.status_code}: {resp.text[:200]}")
            return None, None
        choices = resp.json().get("choices") or []
        text = (choices[0].get("message", {}).get("content", "") if choices else "").strip()
        if text:
            return text, model
        print(f"[error] OpenAI-compat {model}: empty response")
        return None, None
    except Exception as e:
        print(f"[error] OpenAI-compat {model} failed: {e}")
        return None, None


_PROVIDER_FUNCS.update(
    gemini=_complete_gemini,
    openai_compat=_complete_openai_compat,
    anthropic=_complete_anthropic,
)


# --------------------------------------------------------------------------- #
# Research note
# --------------------------------------------------------------------------- #
def generate_report(payload: dict) -> str:
    """
    payload: dict with keys like fundamentals, price_stats, relative_valuation,
    analyst_data, insider_activity, macro_context.
    Returns markdown report text.
    """
    try:
        prompt = REPORT_TEMPLATE.format(data_json=json.dumps(payload, indent=2, default=str))
        text, model = _llm_complete(SYSTEM_PROMPT, prompt, max_tokens=2000)
        if not text:
            return _template_report(payload, reason="AI provider unavailable")

        header = (
            f"# AI-Generated Research Note — {payload.get('ticker', '')}\n\n"
            f"*Interpretation generated by {model} from objective data. "
            f"Analyst consensus figures, where shown, are real analyst opinions.*\n\n"
        )
        return header + text
    except Exception as e:
        print(f"[error] Report generation: unexpected error — using template report: {e}")
        return _template_report(payload, reason=str(e))


def _template_report(payload: dict, reason: str = "") -> str:
    """Structured report built from collected data when AI is unavailable."""
    ticker = payload.get("ticker", "")
    fundamentals = payload.get("fundamentals") or {}
    price_stats = payload.get("price_stats") or {}
    rel_val = payload.get("relative_valuation") or {}
    macro = payload.get("macro_context") or {}
    analysts = payload.get("analyst_consensus") or {}
    insider = payload.get("insider_activity") or {}
    transcript = payload.get("transcript_analysis") or {}

    lines = [
        f"# Research Note — {ticker}",
        "",
        "*Template report generated from collected data (AI interpretation unavailable).*",
    ]
    if reason:
        lines.append(f"*Reason: {reason}*")
    lines.append("")

    lines.append("## Company Snapshot")
    if fundamentals.get("available") is False:
        lines.append(f"- Data unavailable: {fundamentals.get('note', 'unknown')}")
    else:
        lines.append(f"- **Company:** {fundamentals.get('company_name', 'N/A')}")
        lines.append(f"- **Sector:** {fundamentals.get('sector', 'N/A')} / {fundamentals.get('industry', 'N/A')}")
        lines.append(f"- **Market cap:** {fundamentals.get('market_cap', 'N/A')}")
    lines.append("")

    lines.append("## Price & Performance")
    if price_stats.get("available") is False:
        lines.append(f"- Data unavailable: {price_stats.get('note', 'unknown')}")
    else:
        lines.append(f"- **Last price:** {price_stats.get('last_price', 'N/A')}")
        lines.append(f"- **1Y return:** {price_stats.get('return_1y', 'N/A')}")
        lines.append(f"- **Annualized vol:** {price_stats.get('annualized_volatility', 'N/A')}")
        lines.append(f"- **Max drawdown:** {price_stats.get('max_drawdown', 'N/A')}")
    lines.append("")

    lines.append("## Valuation vs Peers")
    if rel_val.get("available") is False:
        lines.append(f"- Data unavailable: {rel_val.get('note', 'No peer data')}")
    elif not rel_val or len(rel_val) <= 1:
        lines.append("- No relative valuation metrics available.")
    else:
        for metric, vals in rel_val.items():
            if metric == "available" or not isinstance(vals, dict):
                continue
            premium = vals.get("premium_vs_peers")
            direction = "premium" if premium and premium > 0 else "discount"
            lines.append(
                f"- **{metric}:** target {vals.get('target')} vs peer median "
                f"{vals.get('peer_median')} ({direction} {abs(premium or 0):.1%})"
            )
    lines.append("")

    lines.append("## Fundamentals")
    if fundamentals.get("available") is False:
        lines.append(f"- Data unavailable: {fundamentals.get('note', 'unknown')}")
    else:
        for label, key in [
            ("P/E (TTM)", "pe_ttm"), ("EV/EBITDA", "ev_ebitda"), ("Gross margin", "gross_margin"),
            ("Operating margin", "operating_margin"), ("ROE", "roe"), ("Rev growth YoY", "revenue_growth_yoy"),
        ]:
            val = fundamentals.get(key)
            if val is not None:
                lines.append(f"- **{label}:** {val}")
    lines.append("")

    lines.append("## Macro Context")
    if macro.get("available") is False:
        lines.append(f"- Data unavailable: {macro.get('note', 'unknown')}")
    else:
        lines.append(f"- **Fed funds:** {macro.get('fed_funds_rate', 'N/A')}")
        lines.append(f"- **10Y yield:** {macro.get('ten_year_yield', 'N/A')}")
        lines.append(f"- **CPI YoY:** {macro.get('cpi_yoy', 'N/A')}")
        lines.append(f"- **Unemployment:** {macro.get('unemployment_rate', 'N/A')}")
    lines.append("")

    lines.append("## Analyst Consensus")
    if analysts.get("available") is False:
        lines.append(f"- Data unavailable: {analysts.get('note', 'unknown')}")
    else:
        lines.append(f"- **Source:** {analysts.get('source', 'N/A')}")
        consensus = analysts.get("consensus") or {}
        if consensus.get("available"):
            lines.append(
                f"- **Overall recommendation:** {consensus.get('overall_recommendation', 'N/A')} "
                f"(Strong Buy: {consensus.get('strong_buy', 0)}, Buy: {consensus.get('buy', 0)}, "
                f"Hold: {consensus.get('hold', 0)}, Sell: {consensus.get('sell', 0)}, "
                f"Strong Sell: {consensus.get('strong_sell', 0)})"
            )
        pt = analysts.get("price_target") or {}
        if pt.get("available"):
            label = "Finnhub" if pt.get("source") == "Finnhub" else pt.get("source", "Analyst")
            line = (
                f"- **Price target ({label}):** mean ${pt.get('mean', 'N/A')}, "
                f"high ${pt.get('high', 'N/A')}, low ${pt.get('low', 'N/A')}"
            )
            if pt.get("current") is not None:
                line += f", current ${pt.get('current')}"
            lines.append(line)
        est = analysts.get("earnings_estimates") or {}
        if est.get("available"):
            lines.append(
                f"- **Next quarter EPS estimate:** {est.get('eps_estimate', 'N/A')} "
                f"(period {est.get('period', 'N/A')}, {est.get('num_analysts', 'N/A')} analysts)"
            )
        fmp_pt = analysts.get("fmp_price_target_consensus")
        if fmp_pt:
            lines.append(f"- **FMP price target consensus:** {fmp_pt}")
        actions = analysts.get("recent_rating_actions") or []
        if actions:
            lines.append(f"- **Recent rating actions (FMP):** {len(actions)} on record")
    lines.append("")

    lines.append("## Insider Activity")
    if insider.get("available") is False:
        lines.append(f"- Data unavailable: {insider.get('note', 'unknown')}")
    else:
        lines.append(f"- **Form 4 filings (6m):** {insider.get('form4_filings_last_6m', 'N/A')}")
    lines.append("")

    if transcript.get("available"):
        lines.append("## Earnings Transcript Highlights")
        lines.append(f"- **Sentiment:** {transcript.get('sentiment', 'N/A')}")
        guidance = transcript.get("management_guidance")
        if isinstance(guidance, dict):
            guidance = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in guidance.items() if v)
        if guidance:
            lines.append(f"- **Guidance:** {guidance}")
        risks = transcript.get("key_risks") or []
        if risks:
            lines.append(f"- **Key risks:** {', '.join(str(r) for r in risks[:5])}")

    return "\n".join(lines)


def _fallback_report(payload: dict) -> str:
    """Alias for template report (backward compatibility)."""
    return _template_report(payload)


# --------------------------------------------------------------------------- #
# Earnings transcript analysis
# --------------------------------------------------------------------------- #
# Primary provider (Gemini) has a 1M-token context, so a whole 8-K exhibit fits
# easily. The cap is just a backstop for a pathological document.
TRANSCRIPT_MAX_CHARS = 40000

# Section headers that mark the start of the legal/boilerplate tail of an 8-K
# exhibit or press release. Everything from the earliest match onward is dropped
# BEFORE the char cap, so the financial content (incl. the Outlook / guidance
# section, which sits just before this boilerplate) keeps priority.
_BOILERPLATE_MARKERS = (
    "non-gaap measures",
    "non-gaap financial measures",
    "use of non-gaap",
    "forward-looking statements",
    "forward looking statements",
    "cautionary statement",
    "safe harbor",
)
_BOILERPLATE_MIN_OFFSET = 2000  # ignore passing mentions near the top

TRANSCRIPT_SYSTEM = """You are an equity research analyst reviewing an earnings call transcript.
Extract structured insights from the transcript only. Do not invent information not present in the text.
Return valid JSON matching the requested schema exactly."""

TRANSCRIPT_PROMPT = """Analyze this earnings call transcript for {ticker}.

Extract:
1. management_guidance — next quarter guidance or outlook. Prefer specifics
   (revenue, EPS, gross margin, opex — with the exact figures and ranges stated).
   Return a short string; null if no guidance is given.
2. key_risks — list of key risks management mentioned
3. sentiment — overall tone: "bullish", "neutral", or "bearish"
4. top_quotes — exactly 3 most important executive quotes, each with "speaker" and "quote"

Return ONLY a JSON object with those keys.

{truncation_note}TRANSCRIPT:
{transcript}
"""

PORTFOLIO_BRIEF_SYSTEM = """You are a portfolio strategist writing a concise weekly brief for an investor.
Use only the data provided. Be direct and actionable. No buy/sell recommendations."""

PORTFOLIO_BRIEF_PROMPT = """Write a weekly portfolio brief covering all holdings below.

Include:
- Portfolio overview (composition, notable movers)
- Key themes across holdings
- Risks to watch this week
- 3 bullet points of what matters most

Holdings data:
{data_json}
"""


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _strip_boilerplate_tail(text: str) -> str:
    """Drop the legal/non-GAAP-explanation tail of an 8-K exhibit, if present."""
    low = text.lower()
    cut = len(text)
    for marker in _BOILERPLATE_MARKERS:
        i = low.find(marker)
        if i >= _BOILERPLATE_MIN_OFFSET:
            cut = min(cut, i)
    trimmed = text[:cut].rstrip()
    # Guard against a false positive that would gut the document.
    return trimmed if len(trimmed) >= _BOILERPLATE_MIN_OFFSET else text


def _truncate_transcript(text: str) -> tuple[str, bool]:
    """Boilerplate-trim, then hard-cap. Returns (text, was_shortened)."""
    stripped = text.strip()
    trimmed = _strip_boilerplate_tail(stripped)
    capped = trimmed[:TRANSCRIPT_MAX_CHARS]
    return capped, len(capped) < len(stripped)


def analyze_transcript(transcript_text: str, ticker: str) -> dict:
    """
    Extract guidance, risks, sentiment, and top quotes from an earnings transcript.
    Returns structured dict; falls back gracefully without an AI provider.
    """
    try:
        if not transcript_text or len(transcript_text.strip()) < 200:
            note = "Transcript too short to analyze"
            print(f"[error] {note} for {ticker}")
            return {"available": False, "note": note}

        truncated, was_truncated = _truncate_transcript(transcript_text)
        print(
            f"[info] transcript {ticker}: {len(transcript_text.strip())} raw chars -> "
            f"{len(truncated)} sent (boilerplate-trim + {TRANSCRIPT_MAX_CHARS}-char cap)"
        )

        if not config.ai_provider_chain():
            note = "No AI provider configured — transcript collected but not analyzed"
            print(f"[error] {note}")
            return {"available": False, "note": note, "char_count": len(transcript_text)}

        truncation_note = (
            "Note: The transcript below has been truncated for brevity; "
            "analyze only the excerpt provided.\n\n"
            if was_truncated
            else ""
        )
        prompt = TRANSCRIPT_PROMPT.format(
            ticker=ticker.upper(),
            truncation_note=truncation_note,
            transcript=truncated,
        )
        raw, _model = _llm_complete(TRANSCRIPT_SYSTEM, prompt, max_tokens=1500)
        if not raw:
            note = "AI call failed for transcript analysis"
            print(f"[error] {note} ({ticker})")
            return {"available": False, "note": note}

        parsed = _parse_json_response(raw)
        return {
            "available": True,
            "ticker": ticker.upper(),
            "management_guidance": parsed.get("management_guidance"),
            "key_risks": parsed.get("key_risks", []),
            "sentiment": parsed.get("sentiment", "neutral"),
            "top_quotes": parsed.get("top_quotes", []),
        }
    except json.JSONDecodeError as e:
        note = f"Failed to parse transcript analysis JSON for {ticker}: {e}"
        print(f"[error] {note}")
        return {"available": False, "note": note}
    except Exception as e:
        note = f"Transcript analysis failed for {ticker}: {e}"
        print(f"[error] {note}")
        return {"available": False, "note": note}


# --------------------------------------------------------------------------- #
# Weekly portfolio brief
# --------------------------------------------------------------------------- #
def generate_portfolio_brief(portfolio_data: list[dict]) -> str:
    """AI weekly brief for all portfolio holdings."""
    try:
        if not portfolio_data:
            return "No portfolio holdings to brief."

        prompt = PORTFOLIO_BRIEF_PROMPT.format(
            data_json=json.dumps(portfolio_data, indent=2, default=str)
        )
        text, _model = _llm_complete(PORTFOLIO_BRIEF_SYSTEM, prompt, max_tokens=1500)
        if not text:
            print("[error] AI: portfolio brief generation failed — using template")
            return _portfolio_brief_template(portfolio_data, reason="AI provider unavailable")
        return f"# Weekly Portfolio Brief\n\n*AI-generated from current holdings and prices.*\n\n{text}"
    except Exception as e:
        print(f"[error] Portfolio brief generation failed: {e}")
        return _portfolio_brief_template(portfolio_data, reason=str(e))


def _portfolio_brief_template(portfolio_data: list[dict], reason: str = "") -> str:
    """Fallback portfolio brief built from holdings data."""
    lines = [
        "# Weekly Portfolio Brief",
        "",
        "*Template brief generated from holdings data (AI unavailable).*",
    ]
    if reason:
        lines.append(f"*Reason: {reason}*")
    lines.append("")

    total_value = sum(p.get("market_value") or 0 for p in portfolio_data)
    total_pnl = sum(p.get("pnl") or 0 for p in portfolio_data)
    lines.append(f"- **Total value:** ${total_value:,.2f}")
    lines.append(f"- **Total P&L:** ${total_pnl:,.2f}")
    lines.append(f"- **Holdings:** {len(portfolio_data)}")
    lines.append("")

    for p in portfolio_data:
        lines.append(
            f"- **{p.get('ticker')}:** {p.get('shares')} shares @ "
            f"${p.get('current_price', 'N/A')} | weight {p.get('weight', 0):.1%} | "
            f"P&L ${p.get('pnl', 0):,.2f}"
        )

    return "\n".join(lines)
