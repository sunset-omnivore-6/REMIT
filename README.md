# REMIT — Local desktop dashboard

Pulls REMIT / UoF outage data from `thermaloutages.sse.com` and renders a
filterable table for **Aldbrough** and **Atwick** (SSE gas storage). Runs
locally on your own machine as a small FastAPI app — no Streamlit, no
redeploys to iterate.

## First-time setup (Windows)

You need Python 3.11+ on PATH (install from python.org if needed).

1. Clone or download this repo to a folder of your choice.
2. Right-click `install_shortcut.ps1` → **Run with PowerShell**.
   - If Windows blocks it: open PowerShell in the repo folder and run
     `powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1`
3. The script will:
   - Create a project-local `.venv` and install dependencies
   - Drop a **REMIT** shortcut on your Desktop

## Daily use

Double-click **REMIT** on your desktop. A small console window opens,
the server starts, and your default browser opens to the dashboard at
`http://127.0.0.1:8765/`. Close the console window to stop the app.

## How the data flow works

- `server/fetch_sse.py` hits `https://thermaloutages.sse.com/api/v1/outages/gasuof`
  using `curl_cffi` (impersonates Chrome's TLS fingerprint) with the exact
  headers and payload captured from a real browser request.
- Successful pulls are written to `data/last_good.json`.
- Every fetch attempt — success or failure — is appended to
  `data/fetch_log.jsonl` for diagnosis.
- The background refresher polls every 5 minutes.
- If a fetch fails, the dashboard keeps showing the last good snapshot and
  shows a banner with the failure reason.

## Why the old Streamlit deploy kept breaking

SSE's WAF blocks by source IP / hosting provider. The 403s come back with
`x-deny-reason: host_not_allowed`. Streamlit Community Cloud runs on shared
cloud IPs that drift in and out of the block. Headers, TLS fingerprints,
and Playwright don't help with this — only the request's origin matters.
Running locally on a residential IP avoids the issue.

## Files

- `run.py` — entrypoint; starts uvicorn and opens the browser.
- `REMIT.bat` — what the desktop shortcut runs.
- `install_shortcut.ps1` — one-time Windows installer.
- `server/` — FastAPI app, scraper, cache, normaliser.
- `web/` — static HTML/CSS/JS frontend.
- `data/` — runtime cache (gitignored).
