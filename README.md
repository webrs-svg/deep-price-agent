# 24/7 Deep Price, Deals & Multi-Hop Flight Scout (`deep-price-agent`)

A unified **Local (Antigravity IDE) + 24/7 Cloud (GitHub Actions + Gemini Grounded Search) + Mobile PWA** multi-agent system for:
1. **✈️ Globally-Generic Multi-Hop Flight Combiner**: Discovers direct routes and tests 2-, 3-, and 4-flight combinations across global hubs (Transpacific, Asian transit, Latin America, Europe, Middle East) with strict 3-hour layover safety buffering, checked bag calculations, Point-of-Sale (POS) currency arbitrage, and pre-populated 1-click links for Skyscanner, Google Flights, and Kayak.
2. **🛒 Product Price & Deal Research**: Live retail price scouting, deal forum coupon discovery (OzBargain, Slickdeals, Reddit), cashback stacking, and fake-sale auditing.

---

## Operating Modes

### 1. ✈️ Multi-Hop Flight Combiner Mode
- **Subagents Dispatched (5 in Parallel)**:
  - `departure-hub-mapper`: Scans departure airport outbound international gateways and partitions candidates into 3 continental corridors.
  - `corridor-a-scout`: Tests non-stop direct flights and single-ticket standard alliance connections on Skyscanner, Google Flights, and Kayak.
  - `corridor-b-scout`: Tests 2- and 3-flight combinations through major intermediate continental mega-hubs (e.g. Tokyo Narita/Haneda, Seoul Incheon, Singapore Changi, Dubai, Doha, London Heathrow, Los Angeles).
  - `corridor-c-scout`: Tests low-cost carriers (Jetstar, Zipair, Scoot, AirAsia, Southwest, Volaris, Alaska, Ryanair, Wizz) combining 2, 3, or 4 flights via secondary hubs.
  - `hacker-stitcher-auditor`: Enforces the **3-hour safety layover buffer** on self-transfers, calculates checked bag fees vs carry-on only, flags transit visas (ESTA, eTA, Schengen), and generates deep search links.
- **True Net Flight Price Formula**:
  $$\text{Net Flight Price} = \text{Base Fare} + \text{Taxes/Fees} + \text{Checked Bag (if toggled)} + \text{Payment Surcharges} - \text{POS Arbitrage/Cashback}$$

### 2. 🛒 Product Price & Deal Mode
- **Subagents Dispatched (3 in Parallel)**:
  - `price-scout`: Live store listings, SKU match, inventory, shipping, and tax.
  - `deal-hunter`: Coupon codes, deal forums, cashback portals, and price-beat guarantees.
  - `trust-auditor`: Price history, fake-sale detection, and authorized vs grey import audit.

---

## Architecture & Interfaces

1. **Always-On Directives ([`AGENTS.md`](./AGENTS.md))**:
   - Universal orchestrator rules, mandatory parallel subagent delegation, 3h layover buffers, and landed price formulas.
2. **Modular Skill & Prompts ([`.agents/skills/deep-price-research/`](./.agents/skills/deep-price-research/))**:
   - Runbooks and prompt templates for all 8 specialized subagents.
3. **Installable Chrome Mobile App ([`dashboards/index.html`](./dashboards/index.html))**:
   - Progressive Web App with mode switcher tabs, flight combiners, live subagent progress tracker, and dynamic checked-bag toggles.
4. **24/7 Cloud Runner ([`cloud/cloud_runner.py`](./cloud/cloud_runner.py) & [`.github/workflows/price_watch.yml`](./.github/workflows/price_watch.yml))**:
   - Scheduled every 6 hours and triggerable on-demand via GitHub Actions `workflow_dispatch`.
