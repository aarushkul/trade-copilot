# event_day — scheduled-macro reaction continuation/fade (Cycle 4)

Registered blind 2026-07-29, before any evaluation. Grid frozen at
registration; any change is a new spec. First registration of this family
and of Cycle 4 (user re-mandate 2026-07-28 ~21:30 ET: new-information
slate under the unchanged binding protocol; the 2026-07-28 authorities
carry over).

## Hypothesis

Scheduled macro releases (FOMC statements, CPI, NFP) are the only
*scheduled* candidates for the trend-day outliers where all measured MNQ
profit lives (cycle-3 meta-finding). The initial post-release reaction
carries tradeable directional information — continuation (follow) or
systematic overreaction (fade) — that unconditional entries lack. If
neither arm clears the gates, scheduled-event reactions are efficiently
priced at 1m and the family closes.

## Event calendar (frozen at registration: research/specs/event_calendar.json)

- 55 scheduled FOMC statement days (14:00 ET), 2019-01-01 → 2025-12-10.
  Unscheduled/emergency releases EXCLUDED (nonstandard release times):
  2019-10-11, 2020-03-03, 2020-03-15.
- 81 CPI + 81 NFP release days (08:30 ET), truncated at 2025-09-30
  (documented Q4-2025 cancellation/reschedules make scheduled ≠ actual).
- Provenance and spot-checks recorded inside the JSON. Event days whose
  session is absent from the corpus (e.g., NFP on Good Friday, market
  closed) produce no event — never patched.

## Event definition (closed bars; sim-1.1 trailing exits, next-bar entry)

Per event day, one candidate signal:

- Anchors by minute_et: FOMC reaction = close@14:14 − close@13:59;
  CPI/NFP reaction = close@09:29 − close@08:29. Both anchor bars must
  exist, else no event.
- Size filter: |reaction| ≥ mv × atr_5m[anchor2] (mv=0 disables).
- Direction = sign(reaction); follow trades it, fade trades against.
- Signal bar = anchor2 + delay bars; must exist and lie in the rth
  window (570–945, fixed — pre-noted: no post-hoc window rescue).
- Stop = init_stop_s × atr_5m[signal] (ATR stop), clamp 5–45 pts.
  Trailing exit per sim-1.1: trail_pts = trail_k × atr_5m[signal],
  ride to force-flat 15:59. One signal per event day.

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| etype | fomc, cpi_nfp, all |
| arm | follow, fade |
| delay | 1, 15, 30 (bars after anchor2) |
| mv | 0.0, 1.0 (× atr_5m) |
| trail_k | 2.0, 3.0 |
| init_stop_s | 1.0, 2.0 |

144 grid points. Gates unchanged; sim_version = sim-1.1;
FEATURE_VERSION = 1.

Scarcity, stated before results: n ceilings are 55 (fomc), 162
(cpi_nfp), 217 (all) — the fomc arm CANNOT reach n ≥ 150 and is
informational only; only cpi_nfp/all points with high event-capture can
mathematically pass. This is accepted at registration; the fomc rows are
never promoted on their own.

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates** → top-2 non-adjacent survivors;
  one validation look spent immediately under the standing authority.
- **No pass** → scheduled-event reactions are priced at 1m; family
  CLOSED; the follow-vs-fade asymmetry and the fomc-arm point estimates
  are recorded as information, never promoted. No re-grid.
- Ambiguity resolves AGAINST the family.

## Known limitations (accepted at registration)

- The calendar is release-day only — no surprise magnitude (consensus vs
  actual). A surprise-conditioned spec would need paid data; not this one.
- CPI and NFP are pooled as one 08:30 archetype; their asymmetry is
  visible in the grid only through the shared arm/delay axes.
- Q4-2025 BLS events dropped (schedule integrity), FOMC kept through
  2025-12-10 (Fed dates are actuals).
