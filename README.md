## ColaFindr24 — Auto Monitor (DACH + FR + LU + NO + SE)

Search multiple marketplaces on a schedule and send WhatsApp alerts for new matches. Results are cached in SQLite and appended to CSV.

### Features
- Selenium headless Chrome scraper
- Sites: mobile.de, AutoScout24 (DE/CH/IT), willhaben.at, leboncoin.fr, finn.no, blocket.se
- Range filters via URL params and .env: year `MIN_YEAR..MAX_YEAR`, km `MIN_KM..MAX_KM`, price `MIN_PRICE..MAX_PRICE`
- Match logic: brand/model OR any single keyword (multilingual) triggers
- De-dup via SQLite (`seen_links.db`), export to CSV (`auto_export_finder.csv`)
- WhatsApp notifications via CallMeBot

### Prerequisites
- Python 3.10+
- Google Chrome installed

### Install
```bash
cd /Users/maki/Desktop/colafinder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure
1) Copy env example and edit:
```bash
cp env.example .env
# edit .env to set PHONE and CALLMEBOT_APIKEY and tunables
```
Key .env options:
- Ranges: `MIN_YEAR`, `MAX_YEAR`, `MIN_KM`, `MAX_KM`, `MIN_PRICE`, `MAX_PRICE`
- Behavior: `HEADLESS=true|false`, `MAX_SEND_PER_RUN`, `SLEEP_BETWEEN_SITES`
- Schedule: `CRON_SCHEDULE` (default `0 */6 * * *`)

2) Edit `search_urls.txt`
- One URL per line. Lines starting with `#` are ignored.
- Build URLs in your browser with your exact filters, paste here, and keep placeholders where useful.
- Placeholders supported:
  - `{min_year}` `{max_year}`
  - `{min_km}` `{max_km}`
  - `{min_price}` `{max_price}`
  - `{kw}` (joined sample keywords)
- Back-compat: `{year}` → `{min_year}`, `{km}` → `{max_km}`, `{price}` → `{max_price}`
- Keep country/region scopes in the URL.

### Run once (test)
```bash
source venv/bin/activate
python monitor_autos.py
```
- Watch debug counts like `[DEBUG] autoscout24 returned 42 raw cards`.
- Output: `auto_export_finder.csv` and `seen_links.db`. WhatsApp requires `CALLMEBOT_APIKEY`.

### Cron — managed via script
Use the helper to install/remove/status using absolute paths and `.env` `CRON_SCHEDULE`.
```bash
# install (uses CRON_SCHEDULE or defaults to every 6h)
/Users/maki/Desktop/colafinder/scripts/manage_cron.sh install

# status / remove / run once now / tail logs
/Users/maki/Desktop/colafinder/scripts/manage_cron.sh status
/Users/maki/Desktop/colafinder/scripts/manage_cron.sh remove
/Users/maki/Desktop/colafinder/scripts/manage_cron.sh run_now
/Users/maki/Desktop/colafinder/scripts/manage_cron.sh tail
```
The cron entry looks like:
```cron
0 */6 * * * /Users/maki/Desktop/colafinder/venv/bin/python /Users/maki/Desktop/colafinder/monitor_autos.py >> /Users/maki/Desktop/colafinder/monitor_autos.log 2>&1
```

### Tips
- Rate limits: increase `SLEEP_BETWEEN_SITES` if throttled.
- Debug: set `HEADLESS=false` to watch the browser; increase `driver` timeout if needed.
- Keywords: `.env` list supports multilingual hints (DE/FR/NO/SE).
- Legal: respect site TOS; intended for personal research.

### Contributing / License
- PRs welcome for new site selectors and URL patterns.
- Licensed under MIT (see `LICENSE`).

### Repo
- GitHub: [`mariospeterman/ColaFindr24`](https://github.com/mariospeterman/ColaFindr24)
