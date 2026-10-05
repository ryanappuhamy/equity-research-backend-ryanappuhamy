"""
SEC EDGAR — insider trading (Form 4 filings).

100% free, official, objective data. No API key needed.
SEC requires a User-Agent header identifying you (any email works).
"""

from __future__ import annotations

import os
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
from requests.exceptions import HTTPError, RequestException, Timeout

import market_cache

# SEC requires "Name email" in the User-Agent and answers 403 without an
# email. Set SEC_USER_AGENT (e.g. "EquityResearch you@yourmail.com") on Render.
SEC_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "EquityResearchProject contact@example.com"),
}

# SEC fair-access limit is 10 requests/second per client; stay under it and
# back off on 429 instead of failing the whole lookup.
_MIN_INTERVAL_S = 0.125
_MAX_RETRIES = 3
_rate_lock = threading.Lock()
_last_request_at = 0.0


def sec_request(url: str, timeout: int = 20) -> requests.Response:
    """GET an SEC URL, throttled and retried on 429. Raises on other HTTP errors."""
    global _last_request_at
    for attempt in range(_MAX_RETRIES + 1):
        with _rate_lock:
            wait = _MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
            if wait > 0:
                time.sleep(wait)
            _last_request_at = time.monotonic()
        r = requests.get(url, headers=SEC_HEADERS, timeout=timeout)
        if r.status_code != 429 or attempt == _MAX_RETRIES:
            r.raise_for_status()
            return r
        retry_after = r.headers.get("Retry-After")
        time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt)
    raise RuntimeError("unreachable")

MAX_FILINGS_TO_PARSE = 12
MAX_TRANSACTIONS = 8
INCLUDED_TRANSACTION_CODES = frozenset({"P", "S", "A", "D", "F", "M"})


_CIK_MAP_TTL_S = 24 * 3600
_cik_map: dict[str, str] = {}
_cik_map_at = 0.0


def _lookup_cik(ticker: str) -> str | None:
    """Ticker -> CIK from SEC's mapping file (kept in memory for a day).

    Returns None only when SEC doesn't know the ticker; network errors raise,
    so callers can tell "no such filer" from "SEC unreachable".
    """
    global _cik_map, _cik_map_at
    if not _cik_map or time.monotonic() - _cik_map_at > _CIK_MAP_TTL_S:
        data = sec_request("https://www.sec.gov/files/company_tickers.json").json()
        _cik_map = {entry["ticker"].upper(): str(entry["cik_str"]).zfill(10) for entry in data.values()}
        _cik_map_at = time.monotonic()
    # SEC writes share classes with a dash: BRK.B -> BRK-B.
    return _cik_map.get(ticker.upper()) or _cik_map.get(ticker.upper().replace(".", "-"))


def _get_cik(ticker: str) -> str | None:
    """Map ticker -> CIK number using SEC's official mapping file."""
    try:
        cik = _lookup_cik(ticker)
        if cik is None:
            print(f"[error] SEC EDGAR: CIK not found for ticker {ticker}")
        return cik
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
    # Bump the version when the parsing changes, so rows cached by the old
    # parser are ignored instead of served for another 24 h.
    cache_key = f"{months_back}m-v3"
    cached = market_cache.get_insider_activity(ticker, cache_key)
    if cached is not None:
        return cached

    result = _fetch_insider_activity(ticker, months_back)
    # Don't pin a transient SEC error (timeout, 429) in the cache for 24 h.
    if result.get("available") or result.get("no_cik"):
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


# Label by the Form 4 transaction code, not the acquired/disposed flag: an RSU
# grant (A) or a vesting (M) is "acquired" but is not an open-market buy, and
# shares withheld for tax (F) are "disposed" but are not a sale.
CODE_LABELS = {
    "P": "Buy",
    "S": "Sell",
    "A": "Award",
    "M": "Exercise",
    "F": "Tax withholding",
    "D": "Disposition",
}


def _action_label(code: str | None) -> str | None:
    normalized_code = (code or "").upper()
    if normalized_code not in INCLUDED_TRANSACTION_CODES:
        return None
    return CODE_LABELS.get(normalized_code)


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

    rows = [(tx, False) for tx in _iter_transactions(root, "nonDerivativeTable")] + [
        (tx, True) for tx in _iter_transactions(root, "derivativeTable")
    ]
    for tx, is_derivative in rows:
        code = (_nested_text(tx, "transactionCoding", "transactionCode") or "").upper()
        # An exercise or RSU vesting is reported twice: the derivative leg (the
        # unit going away) and the common-stock leg. Keep only the stock leg.
        if is_derivative and code == "M":
            continue
        action = _action_label(code)
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
                "code": code,
                "amount": amount,
                "shares": shares,
                "dollar_value": dollar_value,
                "date": tx_date,
                "transaction_date": tx_date,
            }
        )

    return _merge_same_day(transactions)


def _merge_same_day(transactions: list[dict]) -> list[dict]:
    """One filing often splits an event into several lines (a sale in lots,
    time- and performance-based RSU grants). Sum lines with the same action
    and date so the table shows one row per insider per event."""
    merged: dict[tuple[str, str], dict] = {}
    for tx in transactions:
        key = (tx["action"], tx["date"])
        if key not in merged:
            merged[key] = dict(tx)
            continue
        row = merged[key]
        if tx["shares"] is not None:
            row["shares"] = (row["shares"] or 0) + tx["shares"]
        if row["dollar_value"] is not None and tx["dollar_value"] is not None:
            row["dollar_value"] = round(row["dollar_value"] + tx["dollar_value"], 2)
        else:
            row["dollar_value"] = None

    for row in merged.values():
        if row["dollar_value"] is not None and row["dollar_value"] > 0:
            row["amount"] = row["dollar_value"]
        elif row["shares"]:
            row["amount"] = _format_shares(row["shares"])
    return list(merged.values())


def _sec_get(url: str, timeout: int = 20) -> requests.Response | None:
    try:
        return sec_request(url, timeout)
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        print(f"[warn] SEC EDGAR request failed for {url}: {e}")
        return None
    except (Timeout, RequestException) as e:
        print(f"[warn] SEC EDGAR request failed for {url}: {e}")
        return None


def _filing_base(cik: str, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"


def _xml_candidates(cik: str, accession: str, primary_document: str) -> list[str]:
    """Likely raw-XML locations, cheapest first (no extra request needed)."""
    base = _filing_base(cik, accession)

    # primaryDocument often points at the XSL-rendered HTML view
    # ("xslF345X06/edgardoc.xml"); the raw XML sits at the filing root under the
    # same file name, so try that first.
    raw_name = primary_document.rsplit("/", 1)[-1]
    return list(dict.fromkeys([
        f"{base}/{raw_name}",
        f"{base}/{primary_document}",
        f"{base}/form4.xml",
        f"{base}/ownership.xml",
    ]))


def _index_candidates(cik: str, accession: str, tried: list[str]) -> list[str]:
    """Every .xml file listed in the filing's index, minus the ones already tried."""
    base = _filing_base(cik, accession)
    candidates: list[str] = []
    index_response = _sec_get(f"{base}/index.json")
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
                if url not in candidates and url not in tried:
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
    def try_urls(urls: list[str]) -> list[dict]:
        for url in urls:
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

    direct = _xml_candidates(cik, accession, primary_document)
    return try_urls(direct) or try_urls(_index_candidates(cik, accession, direct))


def _fetch_insider_activity(ticker: str, months_back: int) -> dict:
    try:
        cik = _lookup_cik(ticker)
        if cik is None:
            return {
                "available": False,
                "no_cik": True,
                "note": f"No SEC filer found for {ticker}. Insider filings (Form 4) exist for US-listed companies, not for ETFs or funds.",
            }

        data = sec_request(f"https://data.sec.gov/submissions/CIK{cik}.json").json()

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

        if not form4_dates:
            note = (
                f"No insider filings (Form 4) for {ticker} in the last {months_back} months. "
                "Foreign issuers that report on Form 20-F are exempt from Form 4."
            )
        else:
            note = (
                "Form 4 = insider transaction filing. Includes open-market trades (P/S), "
                "awards (A), dispositions (D), tax withholding (F), and option exercises (M)."
            )
        return {
            "available": True,
            "form4_filings_last_6m": len(form4_dates),
            "most_recent_form4": form4_dates[0] if form4_dates else None,
            "transactions": transactions,
            "note": note,
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
