# REMIT URL Hosting Investigation — Diagnostic Record

> **Purpose of this document.** Future maintainers and LLMs picking up this
> project need to know two things: (1) what the REMIT data source is and
> how the dashboard consumes it, and (2) that the question "does SSE block
> datacenter IPs?" was assumed-yes throughout development on contaminated
> evidence, and the answer is genuinely unknown. Read the *"What I got
> wrong"* section before re-running any of the prior reasoning.

---

## 1. Project context

This repository is a custom dashboard for two SSE Thermal gas storage
sites — **Aldbrough** and **Atwick** (Hornsea cluster, East Yorkshire).
It consumes REMIT / UoF (Urgent Market Message / Use of Facility) notices
published by SSE Thermal. Under EU/UK REMIT II these notices are public,
immediate, and trade-actionable; the goal of the dashboard is to give a
trader the operational view (per-direction capacity, transitions,
conflicts) faster than the source site does.

The application was originally a Streamlit app deployed on Streamlit
Community Cloud (`app.py` in the repo root). It was rewritten as a
FastAPI + vanilla-JS dashboard (`server/` + `web/`) because the Streamlit
deploy was unreliable. Why it was unreliable is the open question this
document is about.

---

## 2. The REMIT data source

### Primary endpoint

```
GET https://thermaloutages.sse.com/api/v1/outages/gasuof
```

This returns paginated JSON. Query parameters (replicated verbatim from
a captured browser request):

| Param | Value used |
|---|---|
| `pageNumber` | 1, 2, 3 ... |
| `pageSize` | `50` (browser default; up to 100 supported) |
| `sortDirection` | `DESC` |
| `sortBy` | `PublicationDateTime` |
| `revisionsReturned` | `Latest` |
| `outageDateMatch` | `CONTAINED` |

### Landing page (used to prime cookies)

```
https://thermaloutages.sse.com/gas-uof
```

The browser visits this first, picks up WAF/session cookies, then makes
the XHR to the `/api/v1/outages/gasuof` endpoint. The scraper in
`server/fetch_sse.py` mimics this: GET landing first, then GET API.

### Wire format

JSON object with an `items` (or `results` / `data` / `outages` /
`records` — defensively unwrapped) array of rows. Each row carries
the fields named below; full schema sample is in this file too
(see *Appendix A*).

Key fields for the dashboard's math:

- `threadId` (string) — REMIT thread identifier, e.g. `ATW_000000000000000001226`
- `messageId` — thread id with revision number appended
- `revisionNumber` (int)
- `generationUnitName` (string) — `"Aldbrough"` or `"Atwick"`. The dashboard's normaliser maps this to the canonical `asset` field.
- `eventStatus` (string) — `"Active"`, `"Inactive"`, or `"Dismissed"`
- `typeOfEvent` (string) — `"Withdrawal unavailability"`, `"Injection unavailability"`, or `"Storage unavailability"`. First word is the category.
- `typeOfUnavailability` — `"Planned"` or `"Unplanned"`
- `eventStart`, `eventStop` (ISO 8601 with Z) — outage window
- `technicalCapacity` (float) — nameplate; *not authoritative*, see below
- `unavailableCapacity` (float) — **the MARGINAL contribution of this REMIT only**
- `availableCapacity` (float) — **the ABSOLUTE system state during this REMIT's window, already accounting for other concurrent REMITs at publication time**
- `unitOfMeasurement` — `"GWh/d"` for flow, `"TWh"` for storage
- `reason`, `remarks` (free text)
- `publicationDateTime` (ISO 8601)

### Capacity semantics (important, don't get this wrong again)

`unavailable_capacity` ≠ `tech_max − available_capacity` in general.
Stacking via `MAX(unavailable)` across overlapping REMITs **undercounts**
because each REMIT's `unavailable_capacity` is its own marginal
contribution — the dashboard correctly uses **`MIN(availableCapacity)`**
across all REMITs active at instant `t`, with a fallback to
`tech_max − SUM(unavailable_capacity)` only when no `availableCapacity`
is reported. This rule is in `web/aggregate.js:computeAvailabilityTimeline`
and mirrors the legacy `app.py:_capacity_at` (lines 729–746).

`Dismissed` REMITs are **excluded** from all capacity math (the legacy
`app.py:2602-2604` filter), which is enforced by `operationalRows()` in
the new code. Forgetting this was a real bug that briefly pinned the
chart at 0 GWh/d before being caught.

Authoritative tech-max values (also in `web/aggregate.js`):

| Site | Withdrawal | Injection | Storage |
|---|---|---|---|
| Aldbrough | 287.78 GWh/d | 293.33 GWh/d | 3.3 TWh |
| Atwick | 130 GWh/d | 30 GWh/d | 3.47 TWh |

Source: legacy `app.py:79-85` (`TECH_CAPACITY_FALLBACK`).

---

## 3. The original problem

The Streamlit Community Cloud deployment was unreliable: it would work
for a day or two, then start returning errors (the user described it as
"breaks every couple of days"). Multiple attempted fixes — exact-browser
header matching, `curl_cffi` Chrome TLS fingerprinting, Playwright to
clear a JS WAF challenge — each appeared to help for a while and then
the symptom returned. By the end the user's `app.py` had a Playwright
fallback path and the deploy was outright broken because Chromium isn't
installed on Streamlit Community Cloud.

The pattern (works locally, breaks in cloud, comes back, breaks again)
suggested an **IP- or ASN-based blocklist** at SSE's WAF that cycles
which datacenter ranges it rejects.

---

## 4. What I got wrong (read this carefully)

The misdiagnosis is the most important part of this record.

### The "confirming" evidence

Throughout the project I claimed I had directly confirmed SSE's
datacenter-IP blocklist. The evidence I cited was an HTTP test from
inside the Claude Code sandbox:

```
GET https://thermaloutages.sse.com/api/v1/outages/gasuof
→ HTTP 403
→ x-deny-reason: host_not_allowed
→ body: "Host not in allowlist"
```

I described the explicit reason header as "the smoking gun" and used
it to justify the entire architecture (local Windows app, residential
ISP, mini-PC purchase, the JP Morgan-perspective business case, etc.).

### Why that evidence was wrong

When properly tested late in the project, I re-ran the same probe
against hosts that *cannot* be on any SSE-style blocklist:

```
https://example.com      → HTTP 403 | x-deny-reason: host_not_allowed | 21B
https://www.google.com   → HTTP 403 | x-deny-reason: host_not_allowed | 21B
https://thermaloutages…  → HTTP 403 | x-deny-reason: host_not_allowed | 21B
https://pypi.org         → HTTP 200 (allowed)
```

Byte-identical 21-byte responses. Same header. The 403 was being
issued by **the Claude Code sandbox's own egress network policy**,
not by SSE. The sandbox only permits a curated allowlist (`pypi`,
`github`, a handful of others); everything else gets that exact
canned response, which happens to look like a WAF block.

So when I "confirmed SSE blocks datacenter IPs," I was actually
reading my own cage and projecting it onto the target.

### What this changes

Every claim in the prior conversation about "SSE blocks
datacenter IPs, confirmed by `x-deny-reason: host_not_allowed`"
is **unsupported**. The Streamlit Cloud failures *might* still
have been caused by SSE blocking cloud IPs — that's a plausible
explanation for the symptom — but I never actually demonstrated it.
Other plausible explanations:

- Streamlit Community Cloud workers being suspended/restarted on
  idle (causing apparent intermittent failures unrelated to SSE)
- IP churn on Streamlit's egress pool (an IP that worked yesterday
  has been replaced by one that didn't)
- The header/TLS workarounds themselves introducing flakiness
- A genuine WAF block keyed on ASN or known-cloud IP ranges

Without a clean test we cannot rank these. The mini-PC business
case, the residential-ISP requirement, the entire hosting
recommendation — all of it rested on the un-validated first
hypothesis.

---

## 5. The decisive test that has not been run

A **public-repo GitHub Actions workflow** that performs the exact
SSE fetch from GitHub's cloud egress and reports the HTTP status.
GitHub Actions is free for public repos, runs on a real datacenter
IP, and is exactly the environment a future "online, no PC" host
would use.

The probe needs to:

1. Run on `ubuntu-latest`.
2. Issue `GET https://thermaloutages.sse.com/gas-uof` to prime cookies.
3. Issue `GET https://thermaloutages.sse.com/api/v1/outages/gasuof?pageNumber=1&pageSize=10&sortDirection=DESC&sortBy=PublicationDateTime&revisionsReturned=Latest&outageDateMatch=CONTAINED` with the captured browser headers (see `server/fetch_sse.py:BROWSER_HEADERS`).
4. Print: HTTP status, all response headers, first 500 bytes of body, any WAF-style headers (`x-deny-reason`, `cf-ray`, `x-azure-ref`, `server`).
5. Optionally repeat using `curl_cffi` with `impersonate=chrome131` to see if TLS-fingerprint impersonation changes the outcome.

**Cost:** £0. **Time:** ~5 minutes to write, one push to run.

### Possible outcomes and what they mean

| Outcome | Interpretation | Implication |
|---|---|---|
| `200` + JSON | SSE accepts cloud IPs unchallenged | Architectural unlock. Full free static-site hosting is viable: GitHub Actions cron → JSON committed to repo → GitHub Pages serves the dashboard. Zero ongoing cost, no machine, no proxy. |
| `403` with **a different body / WAF header** than the sandbox 21-byte response | SSE genuinely blocks GitHub's egress range | Confirms the original hypothesis. Hosting needs either a residential ISP (mini-PC / Tailscale) or a residential proxy (~£1–3/mo at current rates). |
| `403` matching the sandbox canned response (would only happen if GitHub Actions imposed a similar egress policy, unlikely) | Not a real test result, retry from another runner | — |
| `200` only on `curl_cffi` impersonate run, not on plain `curl` | SSE filters on TLS fingerprint, not IP | Hosting is free if the cron uses `curl_cffi`. |
| Cloudflare interstitial / JS challenge | SSE is using a managed WAF challenge | Static cron fetch insufficient; need either a residential proxy or a headless-browser worker (more complex). |

### Why this matters operationally

If the probe returns `200`, the dashboard can be hosted entirely on
free infrastructure — GitHub Actions for the scheduled fetch, GitHub
Pages for the static frontend, a JSON file in the repo as the data
contract — and the in-flight £60–100 mini-PC business case becomes
unnecessary. The architectural decision being made *should not happen*
until the probe has run.

---

## 6. Architectural prerequisite for the static-site path

If the probe returns `200`, the migration is small but specific. The
existing code is already ~90% client-side — the entire dashboard
(`web/aggregate.js`, `web/app.js`) computes its dials, charts,
transitions and conflicts from a plain rows array. The server's job
is only: fetch → normalise → cache → serve. To go static:

1. Move `server/fetch_sse.py` + `server/normalise.py` into a small
   Python script that runs in the Action and writes
   `data/latest.json` (rows + fetched_at + diagnostics).
2. Commit `data/latest.json` from the Action on a 5–15 minute cron.
3. Point the frontend's `loadData()` (currently `fetch('/api/data')`)
   at the static `data/latest.json` URL.
4. Drop FastAPI entirely; serve `web/` and `data/` from GitHub Pages.

If the probe returns a real `403`, the same architecture still works
with the addition of a residential proxy on the fetch step (the cron
still runs on GitHub, but the outgoing HTTP goes via the proxy).

---

## 7. Things confirmed by direct user observation

These are genuinely observed, not inferred:

- Running locally on the developer's residential Windows machine, the
  scrape succeeds reliably. The dashboard shows real Aldbrough/Atwick
  REMIT data.
- The Streamlit Cloud deployment was unreliable in a way consistent with
  but not uniquely attributable to a WAF block.
- When the developer's PC slept overnight, the FastAPI background
  refresher silently stopped ticking (no failures logged for 8 hours,
  then a DNS resolution error on first attempt after wake, then a
  successful refresh ~14 seconds later). This is OS sleep suspending
  the Python process, **not** a WAF event.

---

## 8. Things assumed and not confirmed

- SSE blocks datacenter IPs by ASN range. (**Probe to test.**)
- The "couple of days" Streamlit cadence reflects WAF cycling
  rather than Streamlit container churn. (**Probe + observation
  on a sustained Actions deploy would test.**)
- A residential-IP VPS would work. (Would require validation per
  vendor — the same probe pointed at the VPS's egress would settle
  it.)
- Major hyperscalers (AWS, Azure, GCP) are all blocked. (No probe
  was run from any of them.)

---

## 9. What a future LLM / contributor should do

1. **Do not act on the "SSE blocks datacenter IPs" claim until the
   probe has been run.** It is the only assumption load-bearing for
   the hosting architecture and it is unverified.
2. **Run the probe (Section 5).** Public-repo GitHub Actions, free,
   one workflow file, no commitments.
3. **Branch from the result** per the table in Section 5.
4. If migrating to the static-site path, the dashboard's data layer
   is *already* a pure function of the rows array — the migration is
   small and well-bounded. Existing dashboard math (min-available
   rule, Dismissed filter, step-function chart, cluster conflicts)
   is correct and must be preserved.

---

## Appendix A — Sample row (verbatim from a successful local fetch)

```json
{
  "id": "b005ec42-5d85-4048-88a2-5076b2a78085",
  "messageId": "ALD_000000000000000001254_004",
  "threadId": "ALD_000000000000000001254",
  "generationUnitName": "Aldbrough",
  "generationUnitEicCode": "55WALDBOROUGH00H",
  "balancingZone": "21YGB-UKGASGRIDW",
  "marketParticipant": "SSE Hornsea Ltd",
  "marketParticipantCode": "A0001033U.UK",
  "technicalCapacity": 287.78,
  "unavailableCapacity": 287.78,
  "availableCapacity": 0,
  "unitOfMeasurement": "GWh/d",
  "typeOfEvent": "Withdrawal unavailability",
  "typeOfUnavailability": "Unplanned",
  "eventStart": "2026-05-31T22:45:00Z",
  "eventStop": "2026-06-02T16:02:00Z",
  "eventStatus": "Inactive",
  "reasonForUnavailability": "Failure",
  "remarks": "Metering Failure",
  "publicationDateTime": "2026-06-02T16:03:04.870196Z",
  "revisionNumber": 4
}
```

## Appendix B — Captured browser request headers

Used verbatim in `server/fetch_sse.py:BROWSER_HEADERS`. Pasting here
so the probe workflow can reproduce them without consulting code:

```
accept: */*
accept-encoding: gzip, deflate, br, zstd
accept-language: en-US,en;q=0.9
dnt: 1
priority: u=1, i
referer: https://thermaloutages.sse.com/gas-uof
sec-ch-ua: "Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "Windows"
sec-fetch-dest: empty
sec-fetch-mode: cors
sec-fetch-site: same-origin
user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36
```

## Appendix C — Why "x-deny-reason: host_not_allowed" was a false positive

The Claude Code sandbox in which the project was developed enforces
a network egress policy. When a request targets a host not on its
allowlist, the proxy returns:

```
HTTP/2 403
x-deny-reason: host_not_allowed
content-length: 21
content-type: text/plain

Host not in allowlist
```

Pypi, GitHub and a handful of other allowlisted hosts pass through;
everything else (including `example.com`, `google.com`, and
`thermaloutages.sse.com`) receives this **identical** canned 403.
Throughout development, this canned response was misinterpreted as
SSE's WAF rejecting datacenter traffic. The byte-identical response
across hosts that could not all be running the same WAF is the
diagnostic tell that any future investigator should look for first.

**Rule of thumb:** Before treating an HTTP response from this
environment as evidence of *anything*, probe at least
`https://example.com` with the same client. If both return the same
21-byte `Host not in allowlist` body, the response is from the
sandbox, not the target.
