"""
Equity Research Platform — backend pipeline (v1, single ticker).

Usage:
    python main.py NVDA
    python main.py NVDA --peers AMD,AVGO,MRVL,INTC   (manual peers if no FMP key)
    uvicorn api:app --reload                        (FastAPI server)

Output:
    output/<TICKER>_report.md      AI research note
    output/<TICKER>_data.json      All raw objective data (for the frontend)
"""

import sys
import os
import json
import argparse

import config
import data_fundamentals as dfund
import data_sec
import data_macro
import data_earnings
import peer_comparison
import ai_report


def run_pipeline(
    ticker: str,
    manual_peers: list[str] | None = None,
    save_files: bool = True,
) -> dict:
    """Run the full research pipeline and return payload + report."""
    ticker = ticker.upper()
    if save_files:
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print(f"Equity Research Pipeline — {ticker}")
    print("=" * 60)

    print("[1/7] Price history & stats...")
    prices = dfund.get_price_history(ticker)
    price_stats = dfund.get_price_stats(prices)

    print("[2/7] Fundamentals...")
    fundamentals = dfund.get_fundamentals(ticker)
    print(f"  source: {fundamentals.get('source')}")

    print("[3/7] Peer comparison...")
    peers = manual_peers or dfund.get_peers(ticker)
    if peers:
        comps = peer_comparison.build_comps_table(ticker, peers)
        rel_val = peer_comparison.relative_valuation(comps, ticker)
        comps_records = comps.to_dict(orient="records")
    else:
        print("  [warn] no peers (set FMP_API_KEY or pass --peers)")
        rel_val, comps_records = {}, []

    print("[4/7] SEC EDGAR insider activity...")
    insider = data_sec.get_insider_activity(ticker)

    print("[5/7] Earnings call transcript...")
    transcript_data = data_earnings.get_earnings_transcript(ticker)
    if transcript_data.get("available"):
        print(f"  exhibit: {transcript_data.get('exhibit')} ({transcript_data.get('filing_date')})")
        transcript_analysis = ai_report.analyze_transcript(
            transcript_data["text"], ticker
        )
    else:
        print(f"  [warn] {transcript_data.get('note')}")
        transcript_analysis = {"available": False, "note": transcript_data.get("note")}

    print("[6/7] Analyst consensus & macro context...")
    analysts = dfund.get_analyst_data(ticker)
    macro = data_macro.get_macro_context()

    print("[7/7] Generating AI research note...")
    payload = {
        "ticker": ticker,
        "fundamentals": fundamentals,
        "price_stats": price_stats,
        "peers": peers,
        "comps_table": comps_records,
        "relative_valuation": rel_val,
        "insider_activity": insider,
        "earnings_transcript": {
            "available": transcript_data.get("available", False),
            "filing_date": transcript_data.get("filing_date"),
            "exhibit": transcript_data.get("exhibit"),
            "is_transcript": transcript_data.get("is_transcript"),
            "char_count": transcript_data.get("char_count"),
            "note": transcript_data.get("note"),
        },
        "transcript_analysis": transcript_analysis,
        "analyst_consensus": analysts,
        "macro_context": macro,
    }
    report = ai_report.generate_report(payload)

    if save_files:
        report_path = os.path.join(config.OUTPUT_DIR, f"{ticker}_report.md")
        data_path = os.path.join(config.OUTPUT_DIR, f"{ticker}_data.json")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        print("=" * 60)
        print(f"Report: {report_path}")
        print(f"Data:   {data_path}")
        print("=" * 60)

    return {"ticker": ticker, "report": report, "data": payload}


def run(ticker: str, manual_peers: list[str] | None = None) -> None:
    run_pipeline(ticker, manual_peers=manual_peers, save_files=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", help="Stock ticker, e.g. NVDA")
    parser.add_argument("--peers", default="", help="Comma-separated peer tickers")
    args = parser.parse_args()

    manual = [p.strip() for p in args.peers.split(",") if p.strip()] or None
    run(args.ticker, manual)
