"""
Weekly portfolio brief scheduler.

Runs every Monday at 08:00 (local time): loads the saved portfolio,
runs risk analysis, generates the AI weekly brief, and writes
output/weekly_brief_<date>.md.
"""

import json
import os
from datetime import datetime

import schedule

import ai_report
import config
import portfolio
import portfolio_risk

SCHEDULE_TIME = "08:00"
SCHEDULE_DAY = "monday"


def _format_weekly_brief_md(
    date_str: str,
    holdings: list[dict],
    risk: dict,
    brief: str,
) -> str:
    """Combine risk analysis and AI brief into a single markdown document."""
    lines = [
        f"# Weekly Portfolio Brief — {date_str}",
        "",
        f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "## Portfolio Holdings",
        "",
    ]

    total_value = sum(p.get("market_value") or 0 for p in holdings)
    total_pnl = sum(p.get("pnl") or 0 for p in holdings)
    lines.append(f"- **Total value:** ${total_value:,.2f}")
    lines.append(f"- **Total P&L:** ${total_pnl:,.2f}")
    lines.append(f"- **Positions:** {len(holdings)}")
    lines.append("")

    for p in holdings:
        lines.append(
            f"- **{p.get('ticker')}:** {p.get('shares')} shares @ "
            f"${p.get('current_price', 'N/A')} | weight {p.get('weight', 0):.1%} | "
            f"P&L ${p.get('pnl', 0):,.2f}"
        )
    lines.append("")

    lines.append("## Risk Analysis")
    lines.append("")
    if risk.get("available") is False:
        lines.append(f"- Data unavailable: {risk.get('note', 'unknown')}")
    else:
        lines.append(f"- **Portfolio vol (1y):** {risk.get('portfolio_annualized_volatility', 'N/A')}")
        scenarios = risk.get("scenarios") or {}
        market = scenarios.get("market_down_20pct", {})
        rates = scenarios.get("rates_up_1pct", {})
        lines.append(
            f"- **Scenario — market -20%:** "
            f"{market.get('estimated_portfolio_return', 'N/A')}"
        )
        lines.append(
            f"- **Scenario — rates +1%:** "
            f"{rates.get('estimated_portfolio_return', 'N/A')}"
        )
        lines.append("")
        lines.append("### Holdings Risk")
        lines.append("")
        for h in risk.get("holdings_risk") or []:
            lines.append(
                f"- **{h.get('ticker')}:** weight {h.get('weight', 0):.1%}, "
                f"vol {h.get('annualized_volatility', 'N/A')}, "
                f"beta {h.get('beta_vs_spy', 'N/A')}, "
                f"risk contrib {h.get('risk_contribution_pct', 'N/A')}"
            )
        corr = risk.get("correlation_matrix")
        if corr:
            lines.append("")
            lines.append("<details><summary>Correlation matrix</summary>")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(corr, indent=2))
            lines.append("```")
            lines.append("")
            lines.append("</details>")
    lines.append("")

    lines.append("## AI Weekly Brief")
    lines.append("")
    lines.append(brief)

    return "\n".join(lines)


def run_weekly_brief() -> dict:
    """
    Load portfolio, run full analysis, generate AI brief, save to output/.

    Mirrors GET /portfolio/analysis + GET /portfolio/brief endpoint logic.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Scheduler: starting weekly brief job ({date_str})")

    try:
        holdings = portfolio.update_prices()
        if not holdings:
            note = "No portfolio saved — weekly brief skipped"
            print(f"[error] Scheduler: {note}")
            return {"available": False, "note": note}

        risk = portfolio_risk.analyze_portfolio_risk(holdings)
        brief = ai_report.generate_portfolio_brief(holdings)

        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        path = os.path.join(config.OUTPUT_DIR, f"weekly_brief_{date_str}.md")
        content = _format_weekly_brief_md(date_str, holdings, risk, brief)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"Scheduler: weekly brief saved to {path}")
        return {
            "available": True,
            "path": path,
            "date": date_str,
            "holdings_count": len(holdings),
            "risk_available": risk.get("available", False),
        }
    except Exception as e:
        note = f"Weekly brief job failed: {e}"
        print(f"[error] Scheduler: {note}")
        return {"available": False, "note": note}


def setup_schedule() -> None:
    """Register the weekly brief job — every Monday at 08:00 local time."""
    getattr(schedule.every(), SCHEDULE_DAY).at(SCHEDULE_TIME).do(run_weekly_brief)
    print(f"Scheduler: registered weekly brief — every {SCHEDULE_DAY} at {SCHEDULE_TIME}")
