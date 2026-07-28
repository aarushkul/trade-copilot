# xmkt — ES→NQ divergence at session extremes (Cycle 3)

Registered blind 2026-07-28, before the ES data is pulled and before any
evaluation. Grid frozen at registration; any change is a new spec. First
registration of this family. Data purchase authorized by the user
2026-07-28 (autonomous spend ≤ remaining free credits, pre-registered
specs only).

## Hypothesis

ES and NQ are near-simultaneous at 1m, but BREADTH structure is not
arbitraged: when ES prints a fresh RTH session extreme while NQ has not
confirmed for many minutes (or vice-versa is deliberately NOT tested —
one direction only, ES as the broad-market reference), the divergence
resolves either by NQ catching up (follow) or by rejection of the move
(fade). If neither arm clears the gates, cross-market price structure at
1m carries no tradeable MNQ edge at these costs and the family closes.

Scope pre-noted: this tests PRICE structure at 1m. Sub-minute lead-lag
is untested here and remains untestable at our cost ceiling — if the
family fails, the verdict is scoped to ≥1m granularity, mirroring the
orderflow scoping precedent.

## Data (pulled under this registration, before evaluation)

- ES (E-mini S&P 500, GLBX.MDP3, ohlcv-1m, raw per-contract symbols) on
  the app's expiry−8d roll rule — identical quarterly calendar to MNQ.
  NEVER continuous symbology (measured divergence on MNQ).
- Range: 2019-05-06 → 2025-12-10 (TRAIN ONLY). Validation/holdout-period
  ES data is deliberately NOT pulled until a validation look is spent, so
  the split fence is physical for this family.
- Files: data/history/xmkt_ES*.json, immutable once pulled, same
  integrity checks as the MNQ pulls (dups/backward/ownership trim).
- **Cost pre-commitment: proceed iff the dry-run quote ≤ $25**; otherwise
  the family is deferred to a user decision and nothing is pulled.

## Event definition (evaluated on closed 1m bars, sim-1 entries next bar)

Per MNQ train session, with ES bars aligned by exact UTC minute to the
MNQ bar timeline (missing ES minute → NaN → no event that bar):

- RTH extremes: running max of highs / min of lows over bars with
  minute_et in [570, 959], per market, within session.
- ES makes a NEW RTH high at bar u iff high_ES[u] > running max before u
  (RTH bars only). Same for lows. NQ likewise on the MNQ bars.
- **Divergence event at bar t**: ES made a new RTH high at some bar in
  (t−b, t] AND NQ's most recent new-RTH-high bar is ≤ t − lag_k (or NQ
  has printed no new high yet this session after 30 RTH bars). Mirror
  for lows. Both conditions require the ES bar at t to exist.
- Signal: follow = trade NQ toward ES's side (long on ES new high);
  fade = against it. One signal per side (high-side/low-side) per
  session — the first divergence event of that side.
- Stop = stop_s × atr_5m[t] (ATR stop — no natural structural level for
  a divergence; stated choice). Engine clamp 5–45 pts. Target =
  target_r × stop. Horizon 60 min fixed. Window gates entry bars.

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| b | 5, 15 (ES extreme recency, bars) |
| lag_k | 15, 30 (NQ staleness, bars) |
| arm | follow, fade |
| window | rth, w2 |
| stop_s | 0.5, 1.0 (× atr_5m) |
| target_r | 1.0, 2.0 |

64 grid points. Gates, sim-1, FEATURE_VERSION (=1): unchanged.

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates** → top-2 non-adjacent survivors;
  one validation look spent immediately (requires pulling the matching
  validation-window ES slice at that moment, which is part of the look).
- **No pass** → cross-market price structure at ≥1m granularity carries
  no MNQ edge at these costs; family CLOSED for cycle 3; no re-grid.
- Ambiguity resolves AGAINST the family.

## Known limitations (accepted at registration)

- ES↔NQ divergence is tested one-way (ES as reference) to halve the
  multiple-testing surface; the reverse direction is simply untested.
- ATR stops, not structural; the "no new NQ high yet + 30 RTH bars"
  bootstrap clause is fixed blind.
- ES degraded-quality days inherit Databento's flags; sessions where the
  ES file lacks bars produce no events rather than being patched.
