# 24/7 Deep Price & Deal Scout (`deep-price-agent`)

A unified **Local (Antigravity IDE) + 24/7 Cloud (GitHub Actions + Gemini API Grounded Search) + Mobile Chrome PWA** multi-agent system for deep online research, live price comparison, coupon/cashback stacking, and historical fake-sale auditing.

## Architecture

1. **Always-On Directives ([`AGENTS.md`](./AGENTS.md))**:
   - Enforces the **Mandatory Parallel Subagent Delegation Rule** (`price-scout`, `deal-hunter`, `trust-auditor`, and `travel-accommodation-scout`).
   - Enforces the **True Net Landed Price Formula**:
     $$\text{Net Landed Price} = \text{Live Sticker Price} + \text{Shipping/Tax} - \text{Promo/Price-Beat} - \text{Cashback/Gift Card Stack}$$
2. **Modular Skill & Prompts ([`.agents/skills/deep-price-research/`](./.agents/skills/deep-price-research/))**:
   - Contains the orchestrator runbook, subagent prompt templates, regional deal/cashback sources, and 24/7 automation setup guide.
3. **Installable Chrome Mobile App ([`dashboards/index.html`](./dashboards/index.html))**:
   - Progressive Web App (PWA) installable via Chrome on Android, iOS, and Desktop.
   - Supports **Instant 3-Subagent Live Search** directly from your phone browser and **24/7 Cloud Watchlist Dispatch**.
4. **24/7 Cloud Runner ([`cloud/cloud_runner.py`](./cloud/cloud_runner.py) & [`.github/workflows/price_watch.yml`](./.github/workflows/price_watch.yml))**:
   - Runs every 6 hours automatically on GitHub Actions (even when your PC is turned off) and updates `data/watchlist.json`, `data/price_history.json`, `reports/`, and `dashboards/index.html`.
