# TelePriceHub — Cloud-ready Telegram price aggregator

Automatically browse supplier bot menus using your Telegram account (Telethon), parse and normalize offers, and compare prices through an **always-on Telegram query bot** backed by Cloudflare Worker + D1.

**You do not need to host anything on your own computer.** GitHub Actions runs the collector four times per day, Cloudflare Worker handles Telegram requests 24/7, and D1 retains offers/history across scheduled jobs. **One-time account creation and credential setup are still required**, because we cannot create a Telegram or Cloudflare account for you.

## Architecture

1. GitHub Actions schedule: `python main.py crawl` (fresh crawl each run; never reuse a permanent visited set).
2. `python main.py sync` uploads verified offers to the private Cloudflare Worker `/ingest` with `SYNC_TOKEN`.
3. Worker stores offers and price changes in D1; offers older than 24 hours are hidden until refreshed.
4. Telegram webhook `/telegram` validates a secret header and restricts access to an allowed user ID; commands: `/help`, `/search netflix`, `/compare netflix`, `/top`, `/status`.

**Security:** Session strings and bot credentials belong in GitHub Secrets. They must never go in the repository or in logs. `/ingest` is authenticated, Telegram webhook verifies its secret, and the query bot fails closed if no users are allowed. The collector never intentionally opens URL buttons, login/pay buttons, or purchase/checkout actions. External supplier bot behavior cannot be guaranteed; test with one permitted bot first.

## Cloud-only setup (no localhost)

### A. Required services

- GitHub account with this repo: `hoafff/TelePriceHub`
- A Telegram user account, a bot created via @BotFather, Telegram API credentials from [my.telegram.org](https://my.telegram.org)
- Cloudflare account with Workers and D1 enabled. Create a D1 database named **telepricehub**. Copy its database ID and your account ID. Enable your `workers.dev` subdomain.
- A Cloudflare API token with permissions to edit Workers scripts and D1 databases, restricted to your account.

### B. GitHub Actions secrets (Settings → Secrets and variables → Actions)

| Secret | Value |
| --- | --- |
| `TELEGRAM_API_ID` | Telegram developer application ID |
| `TELEGRAM_API_HASH` | Telegram developer application hash |
| `TELEGRAM_STRING_SESSION` | One-time Telethon StringSession created using `generate_session.py` |
| `BOT_TOKEN` | Your query bot token (@BotFather) |
| `ALLOWED_USER_IDS` | Your Telegram numeric user ID; comma-delimit for multiple users |
| `TELEGRAM_WEBHOOK_SECRET` | Long random letters/digits/`_`/`-`; independent of bot token |
| `SYNC_TOKEN` | Different high-entropy random secret for ingestion |
| `CLOUDFLARE_API_TOKEN` | Limited Cloudflare API token |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| `CF_D1_DATABASE_ID` | D1 database UUID |
| `WORKER_URL` | Complete URL, e.g. `https://telepricehub-bot.YOUR_SUBDOMAIN.workers.dev` |
| `FX_USD_VND` | Optional manually chosen number, e.g. **your verified rate**; otherwise USD is not compared with VND |
| `FX_USDT_VND` | Optional separately chosen USDT/VND rate |
| `GEMINI_API_KEY` | Optional; leave blank if not using Gemini |

**Actions repository variable** (`Variables`, NOT Secrets): `SUPPLIER_BOTS` = `@supplier_a_bot,@supplier_b_bot`. Only collect from sources you are permitted to access. Never use multiple Telegram accounts to circumvent rate limits.

For the one-time `TELEGRAM_STRING_SESSION`, run `python generate_session.py` once in a trusted interactive environment such as GitHub Codespaces or your PC. Enter your own phone/OTP and store the resulting string directly in the GitHub Secret. **This is one-time registration, not localhost hosting.** Anyone with this session can access your Telegram account; use a dedicated account if feasible.

### C. Deploy

1. On GitHub open **Actions → TelePriceHub — Deploy Cloudflare Worker → Run workflow**. It applies `cloud/schema.sql`, deploys the Worker, configures its secrets, and registers the Telegram webhook.
2. In a browser open `https://telepricehub-bot.YOUR_SUBDOMAIN.workers.dev/health`. Expected JSON: `{"ok":true,"service":"TelePriceHub"}`.
3. Run **Actions → TelePriceHub — Cloud Crawler → Run workflow**. The tests run first, followed by a live crawl and upload to D1. Read the job logs; they must not show Telegram session values.
4. Message your bot: `/status`, `/search netflix`, or `/compare netflix`.

After setup, the bot works independently of your computer. GitHub Actions cron may start late or skip runs under load; the 24-hour freshness rule prevents very old prices from being presented as current. This is a practical zero-localhost deployment, **not** a promise of guaranteed real-time provider updates.

### D. Common issues

- **Missing secret:** CI aborts with the name of the missing variable instead of claiming success with mock data.
- **Cloudflare D1 migration failed:** Check that D1 database is named `telepricehub`, database UUID is correct, and token has D1 Edit.
- **Bot no replies:** Inspect the deployment run's `setWebhook` step, confirm `WORKER_URL`, `ALLOWED_USER_IDS` and webhook secret.
- **No prices:** Check the crawler workflow and whether Telegram bot requires extra confirmation, payment, CAPTCHA or non-standard menu buttons. The crawler never bypasses those.
- **USD vs VND:** No comparison without explicit FX settings, so prices cannot be incorrectly sorted as raw values.
- **Data appears stale:** Only available offers seen within `MAX_AGE_HOURS` (default 24) are considered for a cheapest-price claim.
- **Live crawl:** Not yet verified with your supplier bots. Start with one and review the logs.

## Local optional developer tests

Local testing is **optional**, never required for production hosting.

```bash
pip install -r requirements.txt
python main.py test
python main.py crawl --mock
python main.py report
```

Code layout: `teleprice/crawler.py` (Telethon), `teleprice/parser.py`, `teleprice/matcher.py`, `teleprice/db.py`, `teleprice/comparator.py`, `teleprice/cloud_sync.py`, `cloud/worker.js`, `cloud/schema.sql`, `cloud/wrangler.toml`, `.github/workflows/crawl.yml` and `deploy-cloud.yml`.

## Limits / known constraints

- Some bots require WebApp login, external links, or complicated stateful workflows. No universal crawler is guaranteed to navigate every provider bot.
- The parser currently extracts a single detail item from each product view. Menus containing multiple different products as unstructured text may need supplier-specific parsers.
- Crawls are scheduled, not continuous, and a failed cron run starts a fresh scan at the next successful attempt; D1 stores historical price changes separately.
- Cloudflare free-plan and GitHub Actions execution limits, provider API rules, and Telegram behavior can change.
