"""
SEC EDGAR — insider trading (Form 4 filings).

100% free, official, objective data. No API key needed.
SEC requires a User-Agent header identifying you (any email works).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
from requests.exceptions import RequestException, Timeout

import market_cache

SEC_HEADERS = {
    "User-Agent": "EquityResearchProject contact@example.com",
}

MAX_FILINGS_TO_PARSE = 12
MAX_TRANSACTIONS = 8
INCLUDED_TRANSACTION_CODES = frozenset({"P", "S", "A", "D", "F", "M"})


def _get_cik(ticker: str) -> str | None:
    """Map ticker -> CIK number using SEC's official mapping file."""
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        r = requests.get(url, headers=SEC_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        for entry in data.values():
            if entry["ticker"].upper() == ticker.upper():
                return str(entry["cik_str"]).zfill(10)
        print(f"[error] SEC EDGAR: CIK not found for ticker {ticker}")
        return None
    except Timeout:
        print(f"[error] SEC EDGAR: timeout fetching CIK mapping for {ticker}")
        return None
    except RequestException as e:
        print(f"[error] SEC EDGAR: request failed fetching CIK for {ticker}: {e}")
        return None
    except Exception as e:
        print(f"[error] SEC EDGAR: unexpected error fetching CIK for {ticker}: {e}")
        return None


def get_insider_activity(ticker: str, months_back: int = 6) -> dict:
    """Recent Form 4 filings with parsed buy/sell transactions when available."""
    ticker = ticker.upper()
    cache_key = f"{months_back}m"
    cached = market_cache.get_insider_activity(ticker, cache_key)
    if cached is not None:
        return cached

    result = _fetch_insider_activity(ticker, months_back)
    market_cache.set_insider_activity(ticker, result, cache_key)
    return result


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(parent: ET.Element | None, name: str) -> str | None:
    if parent is None:
        return None
    for child in parent:
        if _local(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None


def _nested_text(parent: ET.Element | None, *names: str) -> str | None:
    node: ET.Element | None = parent
    for name in names:
        node = next((child for child in (node or []) if _local(child.tag) == name), None)
    if node is None:
        return None
    text = (node.text or "").strip()
    return text or None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _format_shares(shares: float) -> str:
    if shares == int(shares):
        return f"{int(shares):,} shares"
    return f"{shares:,.2f} shares"


def _transaction_total_value(tx: ET.Element) -> float | None:
    for path in (
        ("value", "value"),
        ("transactionTotalValue", "value"),
    ):
        total = _parse_float(_nested_text(tx, "transactionAmounts", *path))
        if total is not None and total > 0:
            return total
    return None


def _action_label(code: str | None, acquired_disposed: str | None) -> str | None:
    normalized_code = (code or "").upper()
    if normalized_code not in INCLUDED_TRANSACTION_CODES and acquired_disposed not in {
        "A",
        "D",
    }:
        return None

    if acquired_disposed == "A":
        return "Buy"
    if acquired_disposed == "D":
        return "Sell"

    code_labels = {
        "P": "Buy",
        "S": "Sell",
        "A": "Award",
        "D": "Disposition",
        "F": "Tax withholding",
        "M": "Option exercise",
    }
    return code_labels.get(normalized_code)


def _owner_role(root: ET.Element) -> str:
    owner = next((child for child in root if _local(child.tag) == "reportingOwner"), None)
    if owner is None:
        return ""

    relationship = next(
        (child for child in owner if _local(child.tag) == "reportingOwnerRelationship"),
        None,
    )
    if relationship is None:
        return ""

    title = _child_text(relationship, "officerTitle")
    if title:
        return title
    if _child_text(relationship, "isDirector") in {"1", "true", "True"}:
        return "Director"
    if _child_text(relationship, "isTenPercentOwner") in {"1", "true", "True"}:
        return "10% Owner"
    if _child_text(relationship, "isOfficer") in {"1", "true", "True"}:
        return "Officer"
    other = _child_text(relationship, "otherText")
    return other or ""


def _owner_name(root: ET.Element) -> str:
    owner = next((child for child in root if _local(child.tag) == "reportingOwner"), None)
    if owner is None:
        return "Unknown insider"
    owner_id = next((child for child in owner if _local(child.tag) == "reportingOwnerId"), owner)
    return _child_text(owner_id, "rptOwnerName") or "Unknown insider"


def _iter_transactions(root: ET.Element, table_tag: str):
    for node in root.iter():
        if _local(node.tag) != table_tag:
            continue
        for child in node:
            if _local(child.tag).endswith("Transaction"):
                yield child


def _parse_form4_xml(xml_text: str, filing_date: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[warn] SEC EDGAR: invalid Form 4 XML: {e}")
        return []

    if _local(root.tag) == "html":
        return []

    name = _owner_name(root)
    role = _owner_role(root)
    transactions: list[dict] = []

    for tx in list(_iter_transactions(root, "nonDerivativeTable")) + list(
        _iter_transactions(root, "derivativeTable")
    ):
        code = _nested_text(tx, "transactionCoding", "transactionCode")
        acquired_disposed = _nested_text(
            tx,
            "transactionAmounts",
            "transactionAcquiredDisposedCode",
            "value",
        )
        action = _action_label(code, acquired_disposed)
        if action is None:
            continue

        shares = _parse_float(
            _nested_text(tx, "transactionAmounts", "transactionShares", "value")
        )
        price = _parse_float(
            _nested_text(tx, "transactionAmounts", "transactionPricePerShare", "value")
        )
        total_value = _transaction_total_value(tx)
        tx_date = (
            _nested_text(tx, "transactionDate", "value")
            or _nested_text(tx, "deemedExecutionDate", "value")
            or filing_date
        )

        dollar_value = None
        if shares is not None and price is not None and price > 0:
            dollar_value = round(shares * price, 2)
        elif total_value is not None:
            dollar_value = round(total_value, 2)

        amount = None
        if dollar_value is None or dollar_value <= 0:
            if shares is not None and shares > 0:
                amount = _format_shares(shares)
            else:
                continue
        else:
            amount = dollar_value

        transactions.append(
            {
                "name": name,
                "role": role,
                "action": action,
                "transaction_type": action,
                "amount": amount,
                "shares": shares,
                "dollar_value": dollar_value,
                "date": tx_date,
                "transaction_date": tx_date,
            }
        )

    return transactions


def _sec_get(url: str, timeout: int = 20) -> requests.Response | None:
    try:
        response = requests.get(url, headers=SEC_HEADERS, timeout=timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response
    except (Timeout, RequestException) as e:
        print(f"[warn] SEC EDGAR request failed for {url}: {e}")
        return None


def _xml_candidates(cik: str, accession: str, primary_document: str) -> list[str]:
    cik_num = str(int(cik))
    acc_nodash = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_nodash}"

    candidates = [
        f"{base}/{primary_document}",
        f"{base}/form4.xml",
        f"{base}/ownership.xml",
    ]

    index_response = _sec_get(f"{base}/{accession}-index.json")
    if index_response is not None:
        try:
            index_data = index_response.json()
            items = index_data.get("directory", {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            for item in items:
                name = item.get("name", "")
                if not name.endswith(".xml"):
                    continue
                if "/xsl" in name.lower():
                    continue
                url = f"{base}/{name}"
                if url not in candidates:
                    candidates.append(url)
        except ValueError as e:
            print(f"[warn] SEC EDGAR: invalid filing index JSON for {accession}: {e}")

    return candidates


def _fetch_form4_transactions(
    cik: str,
    accession: str,
    primary_document: str,
    filing_date: str,
) -> list[dict]:
    for url in _xml_candidates(cik, accession, primary_document):
        response = _sec_get(url)
        if response is None:
            continue
        content_type = (response.headers.get("Content-Type") or "").lower()
        text = response.text
        if "html" in content_type or text.lstrip().startswith("<!DOCTYPE html"):
            continue
        parsed = _parse_form4_xml(text, filing_date)
        if parsed:
            return parsed
    return []


def _fetch_insider_activity(ticker: str, months_back: int) -> dict:
    try:
        cik = _get_cik(ticker)
        if cik is None:
            return {"available": False, "note": f"CIK not found for {ticker}"}

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(url, headers=SEC_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        documents = recent.get("primaryDocument", [])

        cutoff = datetime.now() - timedelta(days=months_back * 30)
        form4_filings = [
            (accession, filing_date, primary_document)
            for form, filing_date, accession, primary_document in zip(
                forms, dates, accessions, documents
            )
            if form == "4" and datetime.strptime(filing_date, "%Y-%m-%d") >= cutoff
        ]

        transactions: list[dict] = []
        for accession, filing_date, primary_document in form4_filings[:MAX_FILINGS_TO_PARSE]:
            transactions.extend(
                _fetch_form4_transactions(cik, accession, primary_document, filing_date)
            )

        transactions.sort(
            key=lambda tx: tx.get("transaction_date") or tx.get("date") or "",
            reverse=True,
        )
        transactions = transactions[:MAX_TRANSACTIONS]

        form4_dates = [filing_date for _, filing_date, _ in form4_filings]

        return {
            "available": True,
            "form4_filings_last_6m": len(form4_dates),
            "most_recent_form4": form4_dates[0] if form4_dates else None,
            "transactions": transactions,
            "note": (
                "Form 4 = insider transaction filing. Includes open-market trades (P/S), "
                "awards (A), dispositions (D), tax withholding (F), and option exercises (M)."
            ),
        }
    except Timeout:
        note = f"SEC EDGAR timeout fetching insider activity for {ticker}"
        print(f"[error] {note}")
        return {"available": False, "note": note}
    except RequestException as e:
        note = f"SEC EDGAR request error for {ticker}: {e}"
        print(f"[error] {note}")
        return {"available": False, "note": note}
    except Exception as e:
        note = f"SEC EDGAR error for {ticker}: {e}"
        print(f"[error] {note}")
        return {"available": False, "note": note}
