# Decisions log — REMIT 2.0

- **Core lift source**: `remit2/core/*` is a verbatim copy of the pure data layer of
  REMIT 1.0 (`app.py` @ prod commit `3c075a5`), produced by `tools/lift_from_v1.py`.
  Only the documented shims differ (session factory, `reprime` callable, undecorated
  `fetch_remit`, injected `now`, no UI colours). Re-run the lifter against a newer 1.0
  commit if its data layer changes; the contract test guards equivalence.
- **Ad-hoc store**: GitHub Contents API against a separate private data repo
  (`remit2-data`), never the app's deployed branch (Cloud redeploys on every commit;
  token blast radius). Token: fine-grained PAT, Contents read/write, that repo only.
  **Renewal reminder: set the expiry date here when the PAT is created.**
- **Access**: viewers = Streamlit Cloud allow-list (read-only); editors = `editors`
  list in app secrets (add/edit/close/cancel, equipment config).
- **Combine rule**: additive unit-out (set union of units) unless covered by a live
  REMIT thread; rate caps as minimum; clamp [0, nameplate].
- **Threshold**: Q1 > 27.5 GWh/d, Q2–Q4 > 55.5 GWh/d, by the ad-hoc start-date quarter.
- **Units**: Hornsea Injection 7.5 GWh/d per comp (linear); Hornsea Withdrawal
  Vortisep 30, Phase 6 100; Aldbrough values-only (placeholders for its units).
- **Timestamp parsing (bug found during the lift)**: 1.0's `normalise()` parsed
  timestamps without `format="ISO8601"`; the API mixes fractional and whole-second
  strings, so rows not matching the first row's format were silently coerced to NaT
  (notices vanished from dials/timeline/recent changes). `remit2.core.normalise`
  uses `format="ISO8601"`; the same one-line fix was ported to 1.0 dev.
- **Design review rev A (implemented)**: the chart shades only capacity that is *out*,
  split into its REMIT part (T − R) and ad-hoc part (R − Avail), coloured and hatched
  by cause, with available capacity as a grey wash and everything before now in grey;
  numbered change markers match the numbered Coming up list; gas-day grid (05:00 UK,
  darker Mondays); headline block = level now, cause, next change; one toolbar with
  the legend and an ad-hoc chip that opens the register; ink (not blue) buttons;
  type scale 34/28/20/15/13/12 at weights 400/600.
- **Attribution fix**: an ad-hoc unit-out no longer counts as binding when a REMIT
  already holds availability at 0 (it removes nothing).
- **Wall screen**: selected by URL — open the app with `?mode=wall` on the wall
  display. Dark tokens, no controls, clock with gas day, refresh every minute.
  Dark cause colours are re-stepped, not reused: Planned `#459cdd`, Unplanned
  `#e06f36`, Ad-hoc `#1dab80` — all ≥ 5.4:1 against the dark bands/plots, CVD ΔE ≥ 10,
  normal-vision ΔE ≥ 16. Cause colours are only ever fills, never text.
- **Storage capacity row (third chart per site)**: working gas capacity in TWh from
  Storage REMITs (same 1.0 semantics: latest revision, Inactive clamp, minimum of
  stated availabilities) plus ad-hoc cavern outages, same combine rule as the rates
  (additive unless covered by a live REMIT thread; set union of caverns).
  Nameplates 3.47 TWh (Hornsea) / 3.3 TWh (Aldbrough). **8 caverns at both sites,
  equal split** (user decision): Hornsea 0.43375 TWh, Aldbrough 0.4125 TWh each.
  Public sources differ (SSE: Atwick 8; Equinor: Aldbrough 9) — the count and sizes
  live in `config/equipment.default.json` and can be corrected there.
  Plant view for storage at both sites ("6 of 8 caverns in service"; REMITs → ≈ caverns).
  Cavern ad-hocs reduce storage only (never withdrawal/injection). Units-only menu.
  Storage REMIT threshold: any unpublished reduction > 0.001 TWh warns (and needs the
  acknowledgement tick). A stored equipment config without a Storage section falls
  back to the defaults for it. Wall screen compacted so six rows fit 1920×1080.
- **Design review B2 — glance wheels (implemented)**: six wheels above the charts
  (one panel per site on its plot tint), drawn as plain SVG in `remit2/ui/wheels.py`.
  Solid colour = how much is left; the charts keep hatched cause colours = why.
  States (agreed defaults): Full ≥ 99.95% (slate), Reduced 50% to just under 100%
  (gold `#D9A600`, dark edge in light mode), **Severe below 50%** (raspberry
  `#C2185B` / dark `#C9427A`, never red so it can't read as Unplanned), Out = 0
  (raspberry-tinted track), **Stale after 15 minutes** without fresh data (grey
  dashed ring). Each state also has a word and an icon. Gold replaced amber, which
  collided with Unplanned vermillion for deuteranopes (ΔE 0.9). The **notch marks
  the next change of any size** in the window. The % never reads 100 unless full,
  nor 0 unless out. Rows lose the big number (the wheel carries it); the row
  headline keeps a small value + cause with references.
- **Wall board (B2)**: 2 sites × 3 measures, each cell = big wheel + level/state/next,
  compact chart, next two changes; fits 1920×1080. Stale data greys the board and
  raises a banner. A watchdog reloads the page if the app stops answering for
  5 minutes (only when the server is reachable again).
- **Wall view / Standard view buttons**: toggle the mode without typing the URL —
  they set or clear `?mode=wall`, so a wall display can still be bookmarked.
- **B2 feedback fixes**: the top strip groups each site's three wheels together
  (columns up to 220px, left-aligned under the site name) instead of spreading
  them across the half, names the site at section-heading size, and puts each site
  on its band colour (the same as its section below) with a gutter between the
  two. On the wall, only the changes listed under a chart get numbered badges
  (the next two); every change keeps its faint line. Badges are spaced by their
  real size plus a gap and carry a 2px surface ring, so close changes never merge.
  The Wall view button no longer clips at wide widths.
