# Doctolib availability monitor

Monitors Doctolib doctor availabilities and sends email notifications via Mailjet when at least one appointment slot is available, or when the script hits an error (HTTP errors, Cloudflare, throttling).

## Requirements

- Python 3.8+
- Mailjet API key and secret, and a verified sender address

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   # or on Windows:  .venv\Scripts\activate
   ```

2. Copy the example config and edit it:

   ```bash
   cp config.example.yaml config.yaml
   ```

3. Set your Mailjet API credentials in the environment (never put them in the config file). For interactive use you can `export` them in the shell; for cron, use a `.env` file (see “Running with cron” below):

   ```bash
   export MJ_APIKEY_PUBLIC="your-api-key"
   export MJ_APIKEY_PRIVATE="your-api-secret"
   ```
   Or copy `env.example` to `.env`, fill it in, and run `chmod 600 .env`.

4. Install dependencies (with the venv activated):

   ```bash
   pip install -r requirements.txt
   ```

## Getting Doctolib IDs

You need `practice_ids`, `agenda_ids`, and `visit_motive_ids` for each doctor you want to monitor.

1. Open the doctor’s Doctolib booking page in your browser (e.g. the “Prendre rendez-vous” page).
2. Open Developer Tools (F12) → **Network** tab.
3. Reload the page or change date/motive and look for a request to `availabilities.json`.
4. From the request URL (or “Copy as cURL”), read:
   - `practice_ids` (e.g. `52101` from `placeId=practice-52101` or query `practice_ids=52101`)
   - `agenda_ids` (e.g. `135369`)
   - `visit_motive_ids` (e.g. `904826`; there can be several, one per motive)

You can also inspect the booking page URL: parameters like `placeId=practice-52101` give `practice_ids=52101`, and `motiveIds[]=904826` gives `visit_motive_ids=904826`. The `agenda_ids` usually appear in the `availabilities.json` request.

## Configuration

Edit `config.yaml`:

- **mailjet**
  - `from_email`: verified sender address (must be verified in Mailjet).
  - `to_emails`: list of addresses that will receive availability and error emails.
- **watchers**: list of doctors to monitor. Each entry:
  - `name`: label used in logs and emails.
  - `practice_ids`: string or list (e.g. `"52101"` or `["52101"]`).
  - `agenda_ids`: string or list (e.g. `"135369"`).
  - `visit_motive_ids`: list of motive IDs (e.g. `[904826]`).
  - `telehealth`: optional, default `false`.
  - `booking_url`: optional; the doctor’s Doctolib booking page. If set, a clickable link is included in both “slot available” and “script issue” emails.
- **interval_seconds**: seconds between each full check (default 300). Ignored when using `--once`.
- **limit**: number of days of slots to request from the API (default 5).
- **start_date**: optional; default is today (YYYY-MM-DD).

## Run

Activate the venv first (`source .venv/bin/activate`), then:

- **Continuous loop** (runs until Ctrl+C):

  ```bash
  python monitor.py
  # or with a custom config:
  python monitor.py --config /path/to/config.yaml
  ```

- **Single run** (for cron):

  ```bash
  python monitor.py --once
  ```

### Running with cron (every 5 minutes, log to file, secrets from file)

1. **Create an env file with your Mailjet secrets** (do not commit it):

   ```bash
   cp env.example .env
   chmod 600 .env
   # Edit .env and set MJ_APIKEY_PUBLIC and MJ_APIKEY_PRIVATE
   ```

2. **Use a cron line that sources `.env` and appends output to a log file**:

   ```cron
   */5 * * * * cd /path/to/doctowatch && . ./.env && .venv/bin/python monitor.py --once >> /path/to/doctowatch/doctowatch.log 2>&1
   ```

   Replace `/path/to/doctowatch` with the real project path (e.g. `$HOME/tools/doctowatch` or `/home/you/doctowatch`). The script logs to stdout, so redirecting with `>> ... 2>&1` writes all output and errors to `doctowatch.log`.

3. **Optional:** add log rotation for `doctowatch.log` (e.g. with `logrotate`) so the file does not grow forever.

## Notifications

- **Slot available**: one email per watcher when at least one slot is found. Subject: `Doctolib: slot available – <watcher name>`. If you set `booking_url` for that watcher, a “Doctor page / Book here” link is included (clickable in HTML).
- **Script issue**: one email when a check fails (non-200, Cloudflare/challenge, invalid JSON, timeout, etc.). Subject: `Doctolib monitor: script issue`. Body includes watcher name (if applicable), error summary, HTTP status when relevant, and a “Doctor page” link when `booking_url` is set.

## License

Use at your own responsibility. Respect Doctolib’s terms of use and rate limits.
