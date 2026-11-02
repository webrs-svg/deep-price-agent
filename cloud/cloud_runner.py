#!/usr/bin/env python3
"""
24/7 Cloud Multi-Agent Orchestrator for Deep Online Price & Deal Comparison
AND Globally-Generic Multi-Hop Flight Search & Combiner.

Modes:
- 'product': 3 parallel subagents (price-scout, deal-hunter, trust-auditor)
- 'flight': 5 parallel subagents (departure-hub-mapper, corridor-a-scout, corridor-b-scout,
            corridor-c-scout, hacker-stitcher-auditor) testing 1/2/3/4-flight combos,
            3h safety layovers, checked bag calculations, and deep booking links.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD_PATH = WORKSPACE_ROOT / "AGENTS.md"
PROMPTS_MD_PATH = (
    WORKSPACE_ROOT
    / ".agents"
    / "skills"
    / "deep-price-research"
    / "references"
    / "subagent-prompts.md"
)
SOURCES_MD_PATH = (
    WORKSPACE_ROOT
    / ".agents"
    / "skills"
    / "deep-price-research"
    / "references"
    / "deal-sources-by-region.md"
)

# Product paths
WATCHLIST_PATH = WORKSPACE_ROOT / "data" / "watchlist.json"
HISTORY_PATH = WORKSPACE_ROOT / "data" / "price_history.json"
REPORTS_DIR = WORKSPACE_ROOT / "reports"
DASHBOARD_PATH = WORKSPACE_ROOT / "dashboards" / "index.html"

# Flight paths
FLIGHT_WATCHLIST_PATH = WORKSPACE_ROOT / "data" / "flight_watchlist.json"
FLIGHT_HISTORY_PATH = WORKSPACE_ROOT / "data" / "flight_history.json"
FLIGHT_REPORTS_DIR = WORKSPACE_ROOT / "reports" / "flights"
FLIGHT_INDEX_PATH = WORKSPACE_ROOT / "reports" / "flights-INDEX.md"

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "item"


def load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required directive file missing: {path}")
    return path.read_text(encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_subagent_templates(prompts_md: str) -> dict[str, str]:
    """Extracts subagent templates using regex on headers containing role backticks."""
    pattern = r"## Subagent.*?`([a-z0-9_-]+)`.*?```markdown\n(.*?)```"
    matches = re.findall(pattern, prompts_md, flags=re.DOTALL)
    templates = {role.strip(): block.strip() for role, block in matches}
    return templates


def render_prompt(template: str, replacements: dict[str, Any]) -> str:
    out = template
    for k, v in replacements.items():
        out = out.replace(f"{{{{{k}}}}}", str(v))
    return out


# =====================================================================
# ACCURATE FLIGHT DATE NORMALIZATION & DEEP SEARCH LINK GENERATORS
# =====================================================================
def normalize_flight_date(date_str: str, default_day: str = "05") -> tuple[str, str, str]:
    """
    Normalizes human/flexible dates into:
    - iso_date: 'YYYY-MM-DD' (e.g. '2027-08-05')
    - yymmdd: 'YYMMDD' (e.g. '270805' required by Skyscanner)
    - readable: '05 Aug 2027'
    """
    if not date_str:
        return "2027-08-05", "270805", "05 Aug 2027"
    s = str(date_str).strip()
    iso_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if iso_match:
        yyyy = iso_match.group(1)
        mm = iso_match.group(2).zfill(2)
        dd = iso_match.group(3).zfill(2)
        month_abbr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(mm) - 1]
        return f"{yyyy}-{mm}-{dd}", f"{yyyy[2:]}{mm}{dd}", f"{dd} {month_abbr} {yyyy}"

    months = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        "january": "01", "february": "02", "march": "03", "april": "04", "june": "06",
        "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12",
    }
    year_match = re.search(r"\b(202\d|203\d)\b", s)
    yyyy = year_match.group(1) if year_match else "2027"

    mm = "08"
    for m_name, m_num in months.items():
        if re.search(rf"\b{m_name}\b", s, re.IGNORECASE):
            mm = m_num
            break

    day_match = re.search(r"\b([12]\d|3[01]|0?[1-9])\b", s.replace(yyyy, ""))
    dd = day_match.group(1).zfill(2) if day_match else default_day
    month_abbr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(mm) - 1]
    return f"{yyyy}-{mm}-{dd}", f"{yyyy[2:]}{mm}{dd}", f"{dd} {month_abbr} {yyyy}"


def build_skyscanner_url(origin: str, dest: str, depart_date: str = "", return_date: str = "") -> str:
    o = origin.strip().lower()
    d = dest.strip().lower()
    dep_iso, dep_yymmdd, _ = normalize_flight_date(depart_date, "05")
    if return_date:
        ret_iso, ret_yymmdd, _ = normalize_flight_date(return_date, "26")
        return f"https://www.skyscanner.com.au/transport/flights/{o}/{d}/{dep_yymmdd}/{ret_yymmdd}/?adultsv2=1&cabinclass=economy&childrenv2=&preferdirects=false&ref=home"
    return f"https://www.skyscanner.com.au/transport/flights/{o}/{d}/{dep_yymmdd}/?adultsv2=1&cabinclass=economy&childrenv2=&preferdirects=false&ref=home"


def build_google_flights_url(origin: str, dest: str, depart_date: str = "", return_date: str = "") -> str:
    o = origin.strip().upper()
    d = dest.strip().upper()
    dep_iso, _, _ = normalize_flight_date(depart_date, "05")
    if return_date:
        ret_iso, _, _ = normalize_flight_date(return_date, "26")
        query = f"Flights from {o} to {d} departing {dep_iso} returning {ret_iso}"
    else:
        query = f"Flights from {o} to {d} departing {dep_iso}"
    return f"https://www.google.com/travel/flights?q={urllib.parse.quote(query)}"


def build_kayak_url(origin: str, dest: str, depart_date: str = "", return_date: str = "") -> str:
    o = origin.strip().upper()
    d = dest.strip().upper()
    dep_iso, _, _ = normalize_flight_date(depart_date, "05")
    if return_date:
        ret_iso, _, _ = normalize_flight_date(return_date, "26")
        return f"https://www.kayak.com.au/flights/{o}-{d}/{dep_iso}/{ret_iso}?sort=price_a"
    return f"https://www.kayak.com.au/flights/{o}-{d}/{dep_iso}?sort=price_a"


async def run_grounded_subagent(
    client: Any,
    role_name: str,
    prompt_text: str,
    system_instruction: str,
) -> str:
    """Executes a single subagent with live Google Search Grounding via google-genai, with automatic Free-Tier fallback."""
    from google.genai import types

    print(f"  [Subagent Start] -> {role_name}")
    attempts = [
        (DEFAULT_MODEL, True),
        ("gemini-2.5-flash", True),
        ("gemini-3.5-flash-lite", True),
        (DEFAULT_MODEL, False),
        ("gemini-3.5-flash-lite", False),
    ]
    seen: set[tuple[str, bool]] = set()
    unique_attempts = [a for a in attempts if not (a in seen or seen.add(a))]

    response = None
    last_exc: Exception | None = None
    for model_name, use_grounding in unique_attempts:
        try:
            cfg = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[types.Tool(google_search=types.GoogleSearch())] if use_grounding else None,
                temperature=0.2,
            )
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt_text,
                config=cfg,
            )
            break
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            if any(k in err_str for k in ("429", "RESOURCE_EXHAUSTED", "quota", "404", "400", "503")):
                print(f"  [Subagent Fallback] {role_name} hit limit on {model_name} (grounding={use_grounding}), attempting fallback...")
                if "429" in err_str and "limit: 0" not in err_str:
                    await asyncio.sleep(1.5)
                continue
            raise

    if response is None and last_exc is not None:
        raise last_exc

    text = response.text or ""
    urls: list[str] = []
    try:
        cand = response.candidates[0]
        gm = getattr(cand, "grounding_metadata", None)
        if gm and getattr(gm, "grounding_chunks", None):
            for chunk in gm.grounding_chunks:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    urls.append(f"- [{getattr(web, 'title', web.uri)}]({web.uri})")
    except Exception:
        pass

    if urls:
        dedup_urls = list(dict.fromkeys(urls))[:12]
        text += "\n\n### Grounded Search Source Links\n" + "\n".join(dedup_urls)

    print(f"  [Subagent Done]  <- {role_name} ({len(text)} chars)")
    return text


# =====================================================================
# PRODUCT MODE SYNTHESIS
# =====================================================================
async def synthesize_net_landed_price(
    client: Any,
    item: dict[str, Any],
    agents_md: str,
    scout_out: str,
    deal_out: str,
    trust_out: str,
) -> dict[str, Any]:
    from google.genai import types
    from pydantic import BaseModel, Field

    class RetailerOffer(BaseModel):
        retailer: str = Field(description="Retailer or store name")
        trust_tier: str = Field(description="Authorized, Marketplace, or Grey Import")
        base_price: float = Field(description="Live listed sticker price")
        shipping: float = Field(description="Shipping + tax/import duty cost (0 if free)")
        promo_discount: float = Field(description="Discount from coupon code or Price-Beat guarantee")
        cashback_amount: float = Field(description="Savings from cashback portal or discounted gift cards")
        net_landed_price: float = Field(description="base_price + shipping - promo_discount - cashback_amount")
        in_stock: bool = Field(description="True if currently in stock")
        url: str = Field(description="Direct URL to the product or deal")
        stack_notes: str = Field(description="Exact promo code, price-beat rule, or cashback stack used")

    class SynthesisResult(BaseModel):
        verdict: str = Field(description="STRONG BUY, FAIR PRICE, or WAIT FOR SALE")
        best_retailer: str
        best_checkout_price: float
        best_net_landed_price: float
        historical_low_price: float | None = None
        deal_stacking_recipe: list[str] = Field(description="Step-by-Step instructions to achieve best_net_landed_price")
        offers: list[RetailerOffer]
        markdown_report: str = Field(description="Complete detailed Markdown comparison report with tables and links")

    synthesis_prompt = f"""
You are the Lead Orchestrator Agent defined in AGENTS.md.
Synthesize the findings from your 3 parallel subagents for:
- Product: {item.get('name')}
- SKU / Variant: {item.get('sku', 'Standard')}
- Region / Currency: {item.get('region', 'AU')} ({item.get('currency', 'AUD')})
- Target Price: {item.get('target_price')}

--- SUBAGENT 1 (price-scout) ---
{scout_out}

--- SUBAGENT 2 (deal-hunter) ---
{deal_out}

--- SUBAGENT 3 (trust-auditor) ---
{trust_out}

Calculate the True Net Landed Price for every verified retailer option:
Net Landed Price = base_price + shipping - promo_discount - cashback_amount.
Provide the structured JSON response including a rich, comprehensive `markdown_report`.
"""
    response = None
    last_exc: Exception | None = None
    for model_name in dict.fromkeys([DEFAULT_MODEL, "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]):
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=synthesis_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=agents_md,
                    response_mime_type="application/json",
                    response_schema=SynthesisResult,
                    temperature=0.1,
                ),
            )
            break
        except Exception as exc:
            last_exc = exc
            if any(k in str(exc) for k in ("429", "RESOURCE_EXHAUSTED", "quota", "404", "503")):
                await asyncio.sleep(1.5)
                continue
            raise
    if response is None and last_exc is not None:
        raise last_exc
    return json.loads(response.text)


# =====================================================================
# FLIGHT MODE SYNTHESIS (INCLUDES DATES & DEEP LINKS)
# =====================================================================
async def synthesize_flight_routes(
    client: Any,
    route_info: dict[str, Any],
    agents_md: str,
    mapper_out: str,
    corridor_a_out: str,
    corridor_b_out: str,
    corridor_c_out: str,
    stitcher_out: str,
) -> dict[str, Any]:
    from google.genai import types
    from pydantic import BaseModel, Field

    class FlightCombination(BaseModel):
        route_summary: str = Field(description="Full routing e.g. SYD ➔ HNL ➔ LAX ➔ SEA")
        deal_depart_date: str = Field(description="Exact depart date e.g. 2027-08-04 or 4 Aug 2027")
        deal_return_date: str = Field(description="Exact return date e.g. 2027-08-25 or 25 Aug 2027 (or 'One-Way')")
        hops: int = Field(description="Number of flight legs: 1 (direct), 2, 3, or 4")
        airlines: str = Field(description="Airlines involved e.g. Jetstar + Southwest + Alaska")
        duration_hours: float = Field(description="Total duration in hours")
        layovers_summary: str = Field(description="Key layover cities and hours e.g. HNL (3.5h), LAX (4.0h)")
        safety_buffer_met: bool = Field(description="True if all self-transfer layovers are >= 3.0 hours")
        ticket_type: str = Field(description="'Single Ticket (Protected)' or 'Self-Transfer (Hacker Fare)'")
        base_fare: float = Field(description="Base ticket fare in requested currency")
        checked_bag_fee: float = Field(description="Checked bag add-on fee (0 if included)")
        net_fare: float = Field(description="base_fare + checked_bag_fee + taxes")
        cheapest_engine: str = Field(description="Skyscanner, Google Flights, Kayak, or Airline Direct")
        skyscanner_price: float | None = None
        google_flights_price: float | None = None
        kayak_price: float | None = None
        skyscanner_url: str = Field(description="Direct search link to Skyscanner")
        google_flights_url: str = Field(description="Direct search link to Google Flights")
        kayak_url: str = Field(description="Direct search link to Kayak")
        direct_booking_url: str | None = Field(default=None, description="Direct airline link or booking link if available")
        visa_warnings: str = Field(description="Transit visa / ESTA / eTA requirements or None")
        pos_arbitrage_note: str = Field(description="Savings if booked in foreign currency or None")

    class FlightSynthesisResult(BaseModel):
        best_route_summary: str
        best_depart_date: str = Field(description="Exact depart date for best deal")
        best_return_date: str = Field(description="Exact return date for best deal")
        best_net_fare: float
        best_engine: str
        verdict: str = Field(description="EXCELLENT DEAL, GOOD FARE, or EXPENSIVE / WAIT")
        currency: str
        combinations: list[FlightCombination]
        deal_booking_guide: list[str] = Field(description="Step-by-step hacker booking instructions")
        markdown_report: str = Field(description="Comprehensive Markdown flight report with tables and deep links")

    origin = route_info.get("origin", "")
    dest = route_info.get("destination", "")
    dep = route_info.get("depart_date", "")
    ret = route_info.get("return_date", "")
    curr = route_info.get("currency", "AUD")
    bag = "Checked Bag Included" if route_info.get("checked_bag") else "Carry-On Only"

    synth_prompt = f"""
You are the Lead Flight Orchestrator following AGENTS.md.
Synthesize the multi-agent flight research for:
- Route: {origin} to {dest} ({route_info.get('trip_type', 'return')})
- Requested Travel Dates: Depart: {dep}, Return: {ret}
- Cabin: {route_info.get('cabin_class', 'Economy')}
- Luggage Mode: {bag}
- Currency: {curr}

--- SUBAGENT 1 (departure-hub-mapper) ---
{mapper_out}

--- SUBAGENT 2 (corridor-a-scout - Direct & Standard Alliance) ---
{corridor_a_out}

--- SUBAGENT 3 (corridor-b-scout - Continental Mega-Hubs) ---
{corridor_b_out}

--- SUBAGENT 4 (corridor-c-scout - LCC & 2/3/4-Flight Hacker Chains) ---
{corridor_c_out}

--- SUBAGENT 5 (hacker-stitcher-auditor - 3h Layover Buffer, Baggage, Visas) ---
{stitcher_out}

Mandatory Rules:
1. Provide exact `deal_depart_date` and `deal_return_date` (e.g. '2027-08-04' and '2027-08-25') for every combination found.
2. Enforce 3.0h safety layover buffer on all self-transfers.
3. Generate valid pre-populated Skyscanner, Google Flights, and Kayak URLs for every combination using exact deal dates.
4. Compare all options (direct, 2-hop, 3-hop, 4-hop) and rank by True Net Flight Fare.
Return ONLY structured JSON matching FlightSynthesisResult.
"""

    response = None
    last_exc: Exception | None = None
    for model_name in dict.fromkeys([DEFAULT_MODEL, "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]):
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=synth_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=agents_md,
                    response_mime_type="application/json",
                    response_schema=FlightSynthesisResult,
                    temperature=0.1,
                ),
            )
            break
        except Exception as exc:
            last_exc = exc
            if any(k in str(exc) for k in ("429", "RESOURCE_EXHAUSTED", "quota", "404", "503")):
                await asyncio.sleep(1.5)
                continue
            raise

    if response is None and last_exc is not None:
        raise last_exc
    return json.loads(response.text)


# =====================================================================
# DASHBOARD & INDEX HTML GENERATION
# =====================================================================
def update_dashboard_html(
    watchlist_data: dict[str, Any],
    history_data: dict[str, Any],
    flight_watchlist_data: dict[str, Any],
    flight_history_data: dict[str, Any],
    now_iso: str,
) -> None:
    if not DASHBOARD_PATH.exists():
        return
    html = DASHBOARD_PATH.read_text(encoding="utf-8")
    latest_offers = history_data.get("records", [])[-50:]
    latest_flights = flight_history_data.get("records", [])[-50:]

    payload = {
        "last_updated": now_iso,
        "watchlist": watchlist_data.get("items", []),
        "offers": latest_offers,
        "flight_watchlist": flight_watchlist_data.get("routes", []),
        "flight_offers": latest_flights,
    }
    replacement = (
        "<!-- BEGIN_AGENT_DATA -->\n  <script>\n    window.PRICE_AGENT_DATA = "
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + ";\n  </script>\n  <!-- END_AGENT_DATA -->"
    )
    updated_html = re.sub(
        r"<!-- BEGIN_AGENT_DATA -->.*?<!-- END_AGENT_DATA -->",
        replacement,
        html,
        flags=re.DOTALL,
    )
    DASHBOARD_PATH.write_text(updated_html, encoding="utf-8")


def update_reports_index(watchlist_items: list[dict[str, Any]]) -> None:
    rows = []
    for w in watchlist_items:
        rep_link = f"[{w.get('latest_report', 'View')}](./{w.get('latest_report')})" if w.get("latest_report") else "—"
        rows.append(
            f"| **{w.get('name')}** | `{w.get('sku', '—')}` | `{w.get('region', 'AU')} ({w.get('currency', 'AUD')})` "
            f"| {w.get('target_price', '—')} | **{w.get('best_recorded_price', '—')}** | {w.get('best_retailer', '—')} "
            f"| {w.get('verdict', '—')} | `{w.get('last_checked', '—')}` | {rep_link} |"
        )
    table_body = "\n".join(rows) if rows else "| *No products researched yet* | — | `AU (AUD)` | — | — | — | — | — | — |"
    content = f"""# Deep Price & Deal Research Reports Index (`INDEX.md`)

> Automatically maintained by the Lead Orchestrator Agent (Local Antigravity + 24/7 Cloud Runner).

---

## Active Watchlist & Latest Research Summary

| Product / Target | SKU / Variant | Region | Target Price | Best Net Landed Price | Best Retailer | Verdict | Last Checked | Latest Report |
| :--- | :--- | :---: | ---: | ---: | :--- | :---: | :---: | :--- |
{table_body}

---

## Quick Links
- **Core Agent Directives**: [`AGENTS.md`](file:///c:/Users/weber/Documents/Travel/AGENTS.md)
- **Flight Reports Index**: [`reports/flights-INDEX.md`](file:///c:/Users/weber/Documents/Travel/reports/flights-INDEX.md)
- **Interactive HTML Dashboard**: [`dashboards/index.html`](file:///c:/Users/weber/Documents/Travel/dashboards/index.html)
"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "INDEX.md").write_text(content, encoding="utf-8")


def update_flight_reports_index(flight_routes: list[dict[str, Any]]) -> None:
    rows = []
    for f in flight_routes:
        rep_link = f"[{f.get('latest_report', 'View')}](./flights/{f.get('latest_report')})" if f.get("latest_report") else "—"
        date_display = f"{f.get('deal_depart_date', f.get('depart_date', '—'))} ➔ {f.get('deal_return_date', f.get('return_date', '—'))}"
        rows.append(
            f"| **{f.get('origin')}** ➔ **{f.get('destination')}** | `{date_display}` | `{f.get('trip_type', 'return')}` | "
            f"`{f.get('best_route_summary', '—')}` | {f.get('hops', '—')} | **{f.get('currency', 'AUD')} {f.get('best_net_fare', '—')}** | "
            f"{f.get('best_engine', 'Skyscanner')} | {'Yes' if f.get('checked_bag') else 'Carry-on'} | `{f.get('last_checked', '—')}` | {rep_link} |"
        )
    table_body = "\n".join(rows) if rows else "| *No flight routes monitored yet* | — | — | — | — | — | — | — | — | — |"
    content = f"""# Flight Search & Hub-Hopping Route Reports Index (`flights-INDEX.md`)

> Automatically maintained by the Lead Flight Orchestrator Agent (Antigravity Local + 24/7 Cloud Runner).

---

## Active Monitored Flight Routes

| Route | Travel Dates Found | Trip Type | Best Route / Combination | Hops | Best Net Fare | Engine | Checked Bag | Last Checked | Report |
| :--- | :---: | :---: | :--- | :---: | ---: | :---: | :---: | :---: | :---: |
{table_body}

---

## Quick Links
- **Directives & Rules**: [`AGENTS.md`](file:///c:/Users/weber/Documents/Travel/AGENTS.md)
- **Product Reports Index**: [`reports/INDEX.md`](file:///c:/Users/weber/Documents/Travel/reports/INDEX.md)
- **Interactive HTML Dashboard**: [`dashboards/index.html`](file:///c:/Users/weber/Documents/Travel/dashboards/index.html)
"""
    FLIGHT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FLIGHT_INDEX_PATH.write_text(content, encoding="utf-8")


def send_webhook_alert(webhook_url: str, message: str) -> None:
    if not webhook_url:
        return
    try:
        payload = json.dumps({"content": message, "text": message}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "DeepPriceAgent/1.0"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        print(f"  [Webhook Warning] Could not send webhook alert: {exc}")


# =====================================================================
# ITEM PROCESSING: PRODUCT MODE
# =====================================================================
async def process_product_item(
    client: Any,
    item: dict[str, Any],
    agents_md: str,
    templates: dict[str, str],
    sources_md: str,
    history_data: dict[str, Any],
    now_iso: str,
    date_str: str,
) -> dict[str, Any]:
    print(f"\n=== [Product Mode] Deep Researching: {item.get('name')} ({item.get('region', 'AU')} / {item.get('currency', 'AUD')}) ===")
    sys_inst = agents_md + "\n\n### Regional Deal Sources Reference\n" + sources_md

    replacements = {
        "PRODUCT_NAME": item.get("name", ""),
        "SKU_OR_SPECS": item.get("sku", item.get("name", "")),
        "REGION": item.get("region", "AU"),
        "CURRENCY": item.get("currency", "AUD"),
        "TARGET_PRICE": item.get("target_price", "Best Available"),
    }

    scout_prompt = render_prompt(templates["price-scout"], replacements)
    deal_prompt = render_prompt(templates["deal-hunter"], replacements)
    trust_prompt = render_prompt(templates["trust-auditor"], replacements)

    scout_out, deal_out, trust_out = await asyncio.gather(
        run_grounded_subagent(client, "price-scout", scout_prompt, sys_inst),
        run_grounded_subagent(client, "deal-hunter", deal_prompt, sys_inst),
        run_grounded_subagent(client, "trust-auditor", trust_prompt, sys_inst),
    )

    synth = await synthesize_net_landed_price(client, item, agents_md, scout_out, deal_out, trust_out)

    slug = slugify(item.get("name", "product"))
    report_filename = f"{slug}-{date_str}.md"
    report_path = REPORTS_DIR / report_filename
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(synth["markdown_report"], encoding="utf-8")

    item["best_recorded_price"] = synth["best_net_landed_price"]
    item["best_retailer"] = synth["best_retailer"]
    item["verdict"] = synth["verdict"]
    item["last_checked"] = now_iso
    item["latest_report"] = report_filename

    for offer in synth.get("offers", []):
        history_data.setdefault("records", []).append(
            {
                "timestamp": now_iso,
                "product_id": item.get("id", slug),
                "product_name": item.get("name"),
                "currency": item.get("currency", "AUD"),
                **offer,
            }
        )

    target_price = item.get("target_price")
    if target_price and synth["best_net_landed_price"] <= float(target_price):
        alert_msg = (
            f"🔥 DEAL ALERT: {item.get('name')} hit {item.get('currency', 'AUD')} "
            f"{synth['best_net_landed_price']} at {synth['best_retailer']} "
            f"(Target: {target_price})!"
        )
        print(alert_msg)
        send_webhook_alert(os.environ.get("ALERT_WEBHOOK_URL", ""), alert_msg)

    return item


# =====================================================================
# ITEM PROCESSING: FLIGHT MODE
# =====================================================================
async def process_flight_item(
    client: Any,
    route_info: dict[str, Any],
    agents_md: str,
    templates: dict[str, str],
    flight_history_data: dict[str, Any],
    now_iso: str,
    date_str: str,
) -> dict[str, Any]:
    origin = route_info.get("origin", "SYD").upper()
    dest = route_info.get("destination", "SEA").upper()
    print(f"\n=== [Flight Mode] Exploring Multi-Hop Combinations: {origin} ➔ {dest} ({route_info.get('depart_date')}) ===")

    replacements = {
        "ORIGIN": origin,
        "ORIGIN_LOWER": origin.lower(),
        "DESTINATION": dest,
        "DEST_LOWER": dest.lower(),
        "DEPART_DATE": route_info.get("depart_date", "Flexible"),
        "RETURN_DATE": route_info.get("return_date", "None"),
        "TRIP_TYPE": route_info.get("trip_type", "return"),
        "CABIN_CLASS": route_info.get("cabin_class", "Economy"),
        "CHECKED_BAG": "1 Checked Bag (23kg)" if route_info.get("checked_bag") else "Carry-on Only",
        "CURRENCY": route_info.get("currency", "AUD"),
    }

    # 1. Step 1: Map departure hubs & corridors
    mapper_prompt = render_prompt(templates["departure-hub-mapper"], replacements)
    mapper_out = await run_grounded_subagent(client, "departure-hub-mapper", mapper_prompt, agents_md)

    # 2. Step 2: Parallel Corridor Scouts (Corridor A, B, and C)
    sys_inst_corridors = agents_md + "\n\n### Hub Topology Context from departure-hub-mapper:\n" + mapper_out
    corridor_a_prompt = render_prompt(templates["corridor-a-scout"], replacements)
    corridor_b_prompt = render_prompt(templates["corridor-b-scout"], replacements)
    corridor_c_prompt = render_prompt(templates["corridor-c-scout"], replacements)

    corridor_a_out, corridor_b_out, corridor_c_out = await asyncio.gather(
        run_grounded_subagent(client, "corridor-a-scout", corridor_a_prompt, sys_inst_corridors),
        run_grounded_subagent(client, "corridor-b-scout", corridor_b_prompt, sys_inst_corridors),
        run_grounded_subagent(client, "corridor-c-scout", corridor_c_prompt, sys_inst_corridors),
    )

    # 3. Step 3: Hacker Stitcher & Layover Auditor (enforces 3h buffer, visas, deep links)
    stitcher_context = (
        agents_md
        + "\n\n### Corridor A Results:\n"
        + corridor_a_out
        + "\n\n### Corridor B Results:\n"
        + corridor_b_out
        + "\n\n### Corridor C Results:\n"
        + corridor_c_out
    )
    stitcher_prompt = render_prompt(templates["hacker-stitcher-auditor"], replacements)
    stitcher_out = await run_grounded_subagent(client, "hacker-stitcher-auditor", stitcher_prompt, stitcher_context)

    # 4. Step 4: Lead Flight Route Synthesizer
    synth = await synthesize_flight_routes(
        client,
        route_info,
        agents_md,
        mapper_out,
        corridor_a_out,
        corridor_b_out,
        corridor_c_out,
        stitcher_out,
    )

    route_slug = slugify(f"{origin}-{dest}")
    report_filename = f"{route_slug}-{date_str}.md"
    report_path = FLIGHT_REPORTS_DIR / report_filename
    FLIGHT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(synth["markdown_report"], encoding="utf-8")

    route_info["best_route_summary"] = synth["best_route_summary"]
    route_info["best_depart_date"] = synth.get("best_depart_date", route_info.get("depart_date"))
    route_info["best_return_date"] = synth.get("best_return_date", route_info.get("return_date"))
    route_info["best_net_fare"] = synth["best_net_fare"]
    route_info["best_engine"] = synth["best_engine"]
    route_info["verdict"] = synth["verdict"]
    route_info["last_checked"] = now_iso
    route_info["latest_report"] = report_filename

    # Record historical flight combinations with exact dates & deep links
    for combo in synth.get("combinations", []):
        deal_dep = combo.get("deal_depart_date") or route_info.get("depart_date", "")
        deal_ret = combo.get("deal_return_date") or route_info.get("return_date", "")
        combo["deal_depart_date"] = deal_dep
        combo["deal_return_date"] = deal_ret

        combo["skyscanner_url"] = build_skyscanner_url(origin, dest, deal_dep, deal_ret)
        combo["google_flights_url"] = build_google_flights_url(origin, dest, deal_dep, deal_ret)
        combo["kayak_url"] = build_kayak_url(origin, dest, deal_dep, deal_ret)

        flight_history_data.setdefault("records", []).append(
            {
                "timestamp": now_iso,
                "origin": origin,
                "destination": dest,
                "depart_date": deal_dep,
                "return_date": deal_ret,
                "currency": route_info.get("currency", "AUD"),
                **combo,
            }
        )

    target_fare = route_info.get("target_price")
    if target_fare and synth["best_net_fare"] <= float(target_fare):
        alert_msg = (
            f"✈️ FLIGHT DEAL ALERT: {origin} ➔ {dest} hit {route_info.get('currency', 'AUD')} "
            f"{synth['best_net_fare']} ({synth['best_route_summary']}) on {synth['best_engine']} "
            f"(Dates: {route_info['best_depart_date']} to {route_info['best_return_date']})!"
        )
        print(alert_msg)
        send_webhook_alert(os.environ.get("ALERT_WEBHOOK_URL", ""), alert_msg)

    return route_info


# =====================================================================
# MAIN ENTRYPOINT
# =====================================================================
async def main_async(args: argparse.Namespace) -> int:
    agents_md = load_text(AGENTS_MD_PATH)
    prompts_md = load_text(PROMPTS_MD_PATH)
    sources_md = load_text(SOURCES_MD_PATH)
    templates = extract_subagent_templates(prompts_md)

    watchlist_data = load_json(
        WATCHLIST_PATH,
        {"schema_version": "1.0", "default_region": "AU", "default_currency": "AUD", "items": []},
    )
    history_data = load_json(HISTORY_PATH, {"schema_version": "1.0", "records": []})

    flight_watchlist_data = load_json(
        FLIGHT_WATCHLIST_PATH,
        {"schema_version": "1.0", "default_currency": "AUD", "routes": []},
    )
    flight_history_data = load_json(FLIGHT_HISTORY_PATH, {"schema_version": "1.0", "records": []})

    if args.dry_run:
        print("✅ Dry-run check passed:")
        print(f"  - Loaded AGENTS.md ({len(agents_md)} bytes)")
        print(f"  - Extracted subagent templates ({len(templates)}): {list(templates.keys())}")
        print(f"  - Active product watchlist items: {len(watchlist_data.get('items', []))}")
        print(f"  - Active flight routes: {len(flight_watchlist_data.get('routes', []))}")
        if args.mode == "flight":
            print(f"  - Flight Mode Params: {args.origin or 'SYD'} ➔ {args.destination or 'SEA'} ({args.depart_date or 'Anytime'})")
        return 0

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        return 1

    from google import genai

    client = genai.Client(api_key=api_key)
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    now_iso = now.isoformat(timespec="seconds")
    date_str = now.strftime("%Y-%m-%d")

    mode = args.mode

    if mode == "flight":
        routes: list[dict[str, Any]] = flight_watchlist_data.setdefault("routes", [])
        if args.origin and args.destination:
            o = args.origin.strip().upper()
            d = args.destination.strip().upper()
            existing = next((r for r in routes if r.get("origin") == o and r.get("destination") == d), None)
            if not existing:
                existing = {
                    "id": slugify(f"{o}-{d}"),
                    "origin": o,
                    "destination": d,
                    "depart_date": args.depart_date or "August 2027",
                    "return_date": args.return_date or "August 2027",
                    "trip_type": args.trip_type or "return",
                    "cabin_class": args.cabin_class or "Economy",
                    "checked_bag": bool(args.checked_bag),
                    "currency": args.currency or flight_watchlist_data.get("default_currency", "AUD"),
                    "target_price": float(args.target_price) if args.target_price else None,
                    "active": True,
                }
                routes.append(existing)
            await process_flight_item(client, existing, agents_md, templates, flight_history_data, now_iso, date_str)
        else:
            active_routes = [r for r in routes if r.get("active", True)]
            if not active_routes:
                print("No active flight routes in data/flight_watchlist.json. Specify --origin and --destination to search.")
                return 0
            for r in active_routes:
                await process_flight_item(client, r, agents_md, templates, flight_history_data, now_iso, date_str)

        flight_watchlist_data["last_updated"] = now_iso
        save_json(FLIGHT_WATCHLIST_PATH, flight_watchlist_data)
        save_json(FLIGHT_HISTORY_PATH, flight_history_data)
        update_flight_reports_index(routes)
        update_dashboard_html(watchlist_data, history_data, flight_watchlist_data, flight_history_data, now_iso)
        print("\n✅ All flight reports, flight watchlist JSON, and interactive HTML dashboard updated.")

    else:
        # Product Mode
        items: list[dict[str, Any]] = watchlist_data.setdefault("items", [])
        if args.product:
            slug = slugify(args.product)
            existing = next((x for x in items if x.get("id") == slug), None)
            if not existing:
                existing = {
                    "id": slug,
                    "name": args.product,
                    "sku": args.sku or args.product,
                    "region": args.region or watchlist_data.get("default_region", "AU"),
                    "currency": args.currency or watchlist_data.get("default_currency", "AUD"),
                    "target_price": float(args.target_price) if args.target_price else None,
                    "active": True,
                }
                items.append(existing)
            await process_product_item(client, existing, agents_md, templates, sources_md, history_data, now_iso, date_str)
        else:
            active_items = [x for x in items if x.get("active", True)]
            if not active_items:
                print("No active items in data/watchlist.json. Nothing to query.")
                return 0
            for item in active_items:
                await process_product_item(client, item, agents_md, templates, sources_md, history_data, now_iso, date_str)

        watchlist_data["last_updated"] = now_iso
        save_json(WATCHLIST_PATH, watchlist_data)
        save_json(HISTORY_PATH, history_data)
        update_reports_index(items)
        update_dashboard_html(watchlist_data, history_data, flight_watchlist_data, flight_history_data, now_iso)
        print("\n✅ All reports, watchlist JSON, and interactive HTML dashboard updated.")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="24/7 Multi-Agent Price & Flight Search Orchestrator")
    parser.add_argument("--mode", choices=["product", "flight"], default="product", help="Operating mode")

    # Product options
    parser.add_argument("--product", help="Ad-hoc product name to research")
    parser.add_argument("--sku", help="Optional exact SKU or model number")
    parser.add_argument("--region", default="AU", help="Region code (e.g., AU, US, UK, EU)")

    # Flight options
    parser.add_argument("--origin", help="Origin airport code or city (e.g., SYD, LHR, JFK)")
    parser.add_argument("--destination", help="Destination airport code or city (e.g., SEA, DPS, NRT)")
    parser.add_argument("--depart-date", help="Departure date or month (e.g., 2027-08-01 or August 2027)")
    parser.add_argument("--return-date", help="Return date or month (e.g., 2027-08-28)")
    parser.add_argument("--trip-type", choices=["return", "one-way"], default="return", help="Trip type")
    parser.add_argument("--cabin-class", default="Economy", help="Cabin class (Economy, Premium, Business)")
    parser.add_argument("--checked-bag", action="store_true", help="Include 1 checked bag (23kg)")
    parser.add_argument("--max-hops", type=int, default=4, help="Maximum flight combination legs (1-4)")

    # Common options
    parser.add_argument("--currency", default="AUD", help="Currency code (e.g., AUD, USD, GBP, EUR)")
    parser.add_argument("--target-price", dest="target_price", help="Optional target price alert threshold")
    parser.add_argument("--dry-run", action="store_true", help="Verify directive files and templates without calling API")
    return parser.parse_args()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main_async(parse_args())))
