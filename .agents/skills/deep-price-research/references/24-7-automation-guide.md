# 24/7 Automation Setup Guide (Cloud + Local)

This system supports **two complementary 24/7 modes** that read the exact same directive files (`AGENTS.md`, `subagent-prompts.md`, and `data/watchlist.json`):

1. **Mode A: True Cloud 24/7 Execution (Runs while your PC is turned off)** via GitHub Actions + Gemini API with Google Search Grounding.
2. **Mode B: Local Antigravity Scheduled Execution (Runs while your PC is on)** via Antigravity's built-in `/automation` sidecar or `schedule` tool.

---

## Mode A: True Cloud 24/7 Setup (Runs when PC is OFF)

### Why this is 100% safe alongside your `nativo_site` repository
- You create a **separate GitHub repository** (e.g., `deep-price-agent`) specifically for this workspace.
- **If the repository is Public**: GitHub Actions minutes are **unlimited and 100% free** (uses `0` minutes from your account quota). Your `GEMINI_API_KEY` stays completely encrypted inside GitHub Repository Secrets.
- **If the repository is Private**: Each scheduled check takes ~45–60 seconds (`1 minute`). Running every 6 hours (`4 times/day`) uses only ~120 minutes/month out of your 2,000 free monthly minutes (~6%), leaving ~1,880 minutes for `nativo_site`.

### Step-by-Step Setup (5 Minutes)

#### 1. Get a Free Gemini API Key
1. Go to [Google AI Studio (`aistudio.google.com/apikey`)](https://aistudio.google.com/apikey).
2. Create an API key (the free tier supports `gemini-3-flash-preview` with Google Search grounding).

#### 2. Push this Folder to a Separate GitHub Repo
Run these commands in `c:\Users\weber\Documents\Travel` (or ask Antigravity to run them for you):
```powershell
git init
git add .
git commit -m "Initialize 24/7 Deep Price Research Agent"
# Create a new repo on GitHub (e.g., deep-price-agent) or via gh cli:
gh repo create deep-price-agent --private --source=. --remote=origin --push
```

#### 3. Add Your Secret Key to the Repository
1. On GitHub, open your new `deep-price-agent` repository → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret**:
   - **Name**: `GEMINI_API_KEY`
   - **Secret**: *(Paste your Google AI Studio API key)*
3. *(Optional)* To receive instant phone/desktop push notifications whenever a price drops below your `target_price`, add a second secret:
   - **Name**: `ALERT_WEBHOOK_URL`
   - **Secret**: A Discord Webhook URL, Slack Incoming Webhook URL, or ntfy.sh URL (e.g., `https://ntfy.sh/your-secret-topic-name`).
   - Additionally, whenever a target price is beat in the cloud, the workflow automatically creates/updates a **GitHub Issue** titled `🔥 Deal Alert: <Product Name>` which triggers an instant GitHub mobile/email notification!

#### 4. How to Trigger Research From Your Phone (When Your PC is Off)
Even between scheduled 6-hour runs, you can research any new product from your phone:
1. Open the **GitHub mobile app** (or browser) → go to `deep-price-agent` → **Actions** → **24/7 Deep Price & Deal Watch**.
2. Tap **Run workflow** and type:
   - `product_query`: e.g., `Sony WH-1000XM5 Black`
   - `region`: e.g., `AU`
   - `currency`: e.g., `AUD`
   - `target_price`: e.g., `399`
3. Within ~60 seconds, the cloud subagents (`price-scout`, `deal-hunter`, `trust-auditor`) will run in parallel, commit the new Markdown report to `reports/`, update `data/watchlist.json`, and refresh `dashboards/index.html`.

#### 5. View Your Interactive HTML Dashboard Anywhere (Optional GitHub Pages)
In your repo **Settings** → **Pages**, set Source to `Deploy from a branch` (`main` / root). You can then bookmark `https://<your-username>.github.io/deep-price-agent/dashboards/` on your phone to view the live interactive comparison dashboard anytime.

---

## Mode B: Local Antigravity Automation (When PC is ON)

### 1. In-Session Flash Sale Polling (`schedule` tool)
While you have a conversation open, you can tell the agent:
> *"Check the price of [Product] every 30 minutes for the next 4 hours and notify me if a deal pops up."*

The agent will use its built-in `schedule` tool (`CronExpression` or `DurationSeconds`) to wake itself up automatically without polling loops.

### 2. Local Background Scheduled Runs (`/automation`)
You can ask the agent:
> *"Set up a local scheduled automation to check my watchlist every morning at 9:00 AM."*

The agent will follow the `automation` skill to create `~/.gemini/config/sidecars/watchlist-price-check/sidecar.json` and provide a one-click link to enable it in the Antigravity Automations Dashboard.
