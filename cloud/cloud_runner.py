#!/usr/bin/env python3
"""
24/7 Cloud Multi-Agent Orchestrator for Deep Online Price & Deal Comparison.

Reads the EXACT same Markdown directive files used by Antigravity locally:
- AGENTS.md
- .agents/skills/deep-price-research/references/subagent-prompts.md
- .agents/skills/deep-price-research/references/deal-sources-by-region.md
- data/watchlist.json

Spawns 3 concurrent Gemini subagents with live Google Search Grounding:
1. price-scout
2. deal-hunter
3. trust-auditor

Synthesizes the True Net Landed Price, updates data/watchlist.json,
data/price_history.json, reports/<slug>-<date>.md, reports/INDEX.md,
and dashboards/index.html.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
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
WATCHLIST_PATH = WORKSPACE_ROOT / "data" / "watchlist.json"
HISTORY_PATH = WORKSPACE_ROOT / "data" / "price_history.json"
REPORTS_DIR = WORKSPACE_ROOT / "reports"
DASHBOARD_PATH = WORKSPACE_ROOT / "dashboards" / "index.html"

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "product"


def load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required directive file missing: {path}")
    return path.read_text(encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_subagent_templates(prompts_md: str) -> dict[str, str]:
    """Parses the ```markdown ... ``` blocks for each subagent from subagent-prompts.md."""
    blocks = re.findall(r"```markdown\n(.*?)```", prompts_md, flags=re.DOTALL)
    roles = ["price-scout", "deal-hunter", "trust-auditor", "travel-accommodation-scout"]
    templates: dict[str, str] = {}
    for idx, role in enumerate(roles):
        if idx < len(blocks):
            templates[role] = blocks[idx].strip()
    return templates


def render_prompt(template: str, item: dict[str, Any]) -> str:
    replacements = {
        "{{PRODUCT_NAME}}": str(item.get("name", "")),
        "{{SKU_OR_SPECS}}": str(item.get("sku", item.get("name", ""))),
        "{{REGION}}": str(item.get("region", "AU")),
        "{{CURRENCY}}": str(item.get("currency", "AUD")),
        "{{TARGET_PRICE}}": str(item.get("target_price", "Best Available")),
    }
    out = template
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out


async def run_grounded_subagent(
    client: Any,
    role_name: str,
    prompt_text: str,
    system_instruction: str,
) -> str:
    """Executes a single subagent with live Google Search Grounding via google-genai, with automatic Free-Tier fallback."""
    from google.genai import types

    print(f"  [Subagent Start] -> {role_name}")
    # Fallback chain:
    # 1. Preferred model (e.g. gemini-3.8-flash) with Google Search grounding
    # 2. gemini-2.5-flash with Google Search grounding (has 500 RPD free grounding quota on Free Tier)
    # 3. gemini-3.8-flash / gemini-3.5-flash-lite without grounding tool if all search quotas are exhausted
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
                print(f"  [Subagent Fallback] {role_name} hit quota/limit on {model_name} (grounding={use_grounding}), trying next fallback...")
                if "429" in err_str and "limit: 0" not in err_str:
                    await asyncio.sleep(1.5)
                continue
            raise

    if response is None and last_exc is not None:
        raise last_exc

    text = response.text or ""
    # Extract grounding URLs if available in metadata
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


async def synthesize_net_landed_price(
    client: Any,
    item: dict[str, Any],
    agents_md: str,
    scout_out: str,
    deal_out: str,
    trust_out: str,
) -> dict[str, Any]:
    """Runs the Lead Orchestrator synthesis step producing both structured JSON and a full Markdown report."""
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
        deal_stacking_recipe: list[str] = Field(description="Step-by-step instructions to achieve best_net_landed_price")
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


def update_dashboard_html(watchlist_data: dict[str, Any], history_data: dict[str, Any], now_iso: str) -> None:
    """Updates the embedded window.PRICE_AGENT_DATA block inside dashboards/index.html."""
    if not DASHBOARD_PATH.exists():
        return
    html = DASHBOARD_PATH.read_text(encoding="utf-8")
    latest_offers = history_data.get("records", [])[-50:]
    payload = {
        "last_updated": now_iso,
        "watchlist": watchlist_data.get("items", []),
        "offers": latest_offers,
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
    """Rebuilds reports/INDEX.md table from the latest watchlist state."""
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
- **Deep Price Research Skill Runbook**: [`.agents/skills/deep-price-research/SKILL.md`](file:///c:/Users/weber/Documents/Travel/.agents/skills/deep-price-research/SKILL.md)
- **Interactive HTML Dashboard**: [`dashboards/index.html`](file:///c:/Users/weber/Documents/Travel/dashboards/index.html)
"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "INDEX.md").write_text(content, encoding="utf-8")


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


async def process_item(
    client: Any,
    item: dict[str, Any],
    agents_md: str,
    templates: dict[str, str],
    sources_md: str,
    history_data: dict[str, Any],
    now_iso: str,
    date_str: str,
) -> dict[str, Any]:
    print(f"\n=== Deep Researching: {item.get('name')} ({item.get('region', 'AU')} / {item.get('currency', 'AUD')}) ===")
    sys_inst = agents_md + "\n\n### Regional Deal Sources Reference\n" + sources_md

    scout_prompt = render_prompt(templates["price-scout"], item)
    deal_prompt = render_prompt(templates["deal-hunter"], item)
    trust_prompt = render_prompt(templates["trust-auditor"], item)

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

    if args.dry_run:
        print("✅ Dry-run check passed:")
        print(f"  - Loaded AGENTS.md ({len(agents_md)} bytes)")
        print(f"  - Extracted subagent templates: {list(templates.keys())}")
        print(f"  - Loaded regional deal sources ({len(sources_md)} bytes)")
        print(f"  - Active watchlist items: {len(watchlist_data.get('items', []))}")
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

    items: list[dict[str, Any]] = watchlist_data.setdefault("items", [])

    # If ad-hoc product query passed via CLI or GitHub Actions workflow_dispatch
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
        await process_item(client, existing, agents_md, templates, sources_md, history_data, now_iso, date_str)
    else:
        active_items = [x for x in items if x.get("active", True)]
        if not active_items:
            print("No active items in data/watchlist.json. Nothing to query.")
            return 0
        for item in active_items:
            await process_item(client, item, agents_md, templates, sources_md, history_data, now_iso, date_str)

    watchlist_data["last_updated"] = now_iso
    save_json(WATCHLIST_PATH, watchlist_data)
    save_json(HISTORY_PATH, history_data)
    update_reports_index(items)
    update_dashboard_html(watchlist_data, history_data, now_iso)
    print("\n✅ All reports, watchlist JSON, and interactive HTML dashboard updated.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="24/7 Cloud Multi-Agent Deep Price Runner")
    parser.add_argument("--product", help="Ad-hoc product name to research and add to watchlist")
    parser.add_argument("--sku", help="Optional exact SKU or model number")
    parser.add_argument("--region", default="AU", help="Region code (e.g., AU, US, UK, EU)")
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
