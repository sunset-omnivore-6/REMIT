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
