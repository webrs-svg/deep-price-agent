---
name: deep-price-research
description: >-
  End-to-end multi-agent runbook for deep online product/travel research, live price comparison,
  coupon/cashback/price-match stacking, fake-discount auditing, and 24/7 watchlist monitoring.
  Activate this skill whenever the user asks to research a product, compare prices, find deals,
  update the watchlist, or configure 24/7 local/cloud price tracking.
---

# Deep Price & Deal Research Skill (`deep-price-research`)

This skill defines the mandatory multi-agent execution procedure for finding the lowest **True Net Landed Price** online and persisting findings across sessions.

---

## Step 1: Context Recovery & Target Normalization

1. **Read Persistent State**:
   - Read [`data/watchlist.json`](file:///c:/Users/weber/Documents/Travel/data/watchlist.json) and [`reports/INDEX.md`](file:///c:/Users/weber/Documents/Travel/reports/INDEX.md) to check if the item is already tracked and see its historical low.
2. **Normalize the Target Product**:
   - Identify the exact **Brand, Model Name, MPN/SKU, Storage/Color/Size Variant, and Release Year**.
   - Note common traps to warn subagents about:
     - Previous-generation models with similar names.
     - Refurbished / Renewed / Open-Box / Ex-Demo listings masquerading as new.
     - Accessory bundles vs. bare unit.
     - Regional voltage/plug or cellular band differences.
   - Confirm the target **Region & Currency** (defaults to `AU` / `AUD` unless specified).

---

## Step 2: Mandatory Parallel Subagent Dispatch

Do **not** perform all searches sequentially in the main agent. Read [`references/subagent-prompts.md`](./references/subagent-prompts.md) and [`references/deal-sources-by-region.md`](./references/deal-sources-by-region.md), then launch **at least 3 subagents in parallel** using `invoke_subagent` (with `TypeName: "research"`):

| Subagent Role | Core Responsibility | Output Returned to Lead |
| :--- | :--- | :--- |
| **1. `price-scout`** | Searches official store, major retailers, specialist shops, and price aggregators (StaticICE, Google Shopping, PriceSpy, CamelCamelCamel) for live in-stock listings, shipping fees, and taxes. | Structured list of 5–10 verified live retailer listings with exact URLs, SKU match, base price, shipping cost, and stock status. |
| **2. `deal-hunter`** | Searches deal forums (OzBargain, Slickdeals, Reddit, HotUKDeals), active coupon codes, signup promos, cashback portals (ShopBack, TopCashback, Rakuten), discounted gift cards, and competitor **Price Beat** policies (e.g., Officeworks 5% Price Beat, JB Hi-Fi "Ask for a Deal" / Price Match, Bunnings). | Verified promo codes, recent community deal benchmarks, active cashback percentages, and step-by-step stacking strategies. |
| **3. `trust-auditor`** | Checks 90–365 day historical low prices to detect artificially inflated MSRPs ("fake sales"), distinguishes authorized Australian/local dealers from grey-market dropshippers (e.g., Kogan/Dick Smith marketplace sellers, TobyDeals, BecexTech), and verifies warranty/returns. | Historical low benchmark, "Buy Now vs. Wait" verdict, and seller trust ratings (`Authorized`, `Marketplace`, `Grey Import`). |
| **4. `travel-accommodation-scout`** *(When target is travel)* | Compares flight/hotel OTAs vs. direct booking perks, loyalty portals, bank travel credits, and regional POS pricing. | Net booking comparison table with cancellation policies and luggage/resort fee inclusions. |

> [!IMPORTANT]
> Wait for all parallel subagents to return their findings before synthesizing the final report. If a subagent returns an unverified or out-of-stock price as the top contender, send a follow-up message or run a targeted verification search.

---

## Step 3: Synthesize & Calculate True Net Landed Price

Combine the subagent findings and rank all options by **Net Effective Landed Price**:

$$\text{Net Landed Price} = \text{Base Price} + \text{Shipping} + \text{Tax/Duty} - \text{Promo Code} - \text{Price-Beat Discount} - \text{Cashback / Gift Card Savings}$$

### Deal-Stacking Verification Checklist
For the #1 and #2 cheapest legitimate options, explicitly document the **Stacking Recipe**:
1. **Price Match / Price Beat**: Can an authorized local retailer with a price-beat guarantee (e.g., Officeworks 5% beat on identical stocked items, or JB Hi-Fi live chat price match) beat a competitor's lower price?
2. **Discounted Gift Cards**: Can the buyer pay using discounted gift cards (e.g., 3%–10% off Ultimate/TCN/retailer gift cards via supermarket promos, Macquarie/Suncorp/RACV/NRMA member portals, or Cashrewards/ShopBack gift card store)?
3. **Cashback Portal**: Which portal currently offers the highest rate for that retailer, and do coupon codes void cashback?
4. **Payment / Card Perks**: Are there Amex Offers, PayPal Pay-in-4 promos, or credit card complimentary extended warranty / price protection perks?

---

## Step 4: Persist Outputs Across All 3 Workspace Layers

Every completed research run **must** update:

1. **Markdown Comparison Report**:
   - Follow the template in [`resources/report-template.md`](./resources/report-template.md).
   - Save to `reports/<product-slug>-<YYYY-MM-DD>.md`.
   - Update [`reports/INDEX.md`](file:///c:/Users/weber/Documents/Travel/reports/INDEX.md) with a link to the new report, best net price, and buy/wait status.
2. **Persistent JSON Watchlist & History**:
   - Add or update the product entry in [`data/watchlist.json`](file:///c:/Users/weber/Documents/Travel/data/watchlist.json).
   - Append the new price records to [`data/price_history.json`](file:///c:/Users/weber/Documents/Travel/data/price_history.json).
3. **Interactive HTML Dashboard**:
   - Update the embedded JSON data block (`window.PRICE_AGENT_DATA`) inside [`dashboards/index.html`](file:///c:/Users/weber/Documents/Travel/dashboards/index.html) so the user can open `dashboards/index.html` directly in any browser (or via GitHub Pages) without needing a local web server.

---

## Step 5: 24/7 Scheduled Monitoring (Local & Cloud)

When the user asks to monitor a product 24/7 or adjust the schedule, consult [`references/24-7-automation-guide.md`](./references/24-7-automation-guide.md) for:
- **Cloud 24/7 Execution (PC Turned Off)**: Running [`cloud/cloud_runner.py`](file:///c:/Users/weber/Documents/Travel/cloud/cloud_runner.py) via [`.github/workflows/price_watch.yml`](file:///c:/Users/weber/Documents/Travel/.github/workflows/price_watch.yml).
- **Local Antigravity Automation (PC On)**: Using the `schedule` tool or `/automation` sidecar.
