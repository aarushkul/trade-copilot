# daily_swing — multi-day momentum/reversal (Cycle 4, research-only)

Registered blind 2026-07-29, before any evaluation. Grid frozen at
registration; any change is a new spec. Cycle-4 family 4 (final slate
item). RESEARCH-ONLY label, stated up front: multi-day holds are
untradeable at the user's current account size (below MNQ overnight
margin); a pass produces knowledge and a future-account option, never an
advisory call under current sizing.

## Hypothesis

Every prior family lived inside one session; multi-day holding — where
overnight gaps, the dominant component of multi-day index P&L, actually
accrue — is the one horizon this corpus supports that was never tested.
Daily momentum (N-day closing-high breakout) or its reversal carries
positive expectancy at k-day holds net of costs — or the daily horizon
is efficient too and cycle 4 ends.

## Fill model sim-2-daily (versioned; golden tests part of this registration)

- Daily series per session from the corpus: RTH open = first bar ≥
  09:30 open; RTH close = last bar ≤ 15:59 close.
- Signal evaluated on session t's completed daily bar; entry = session
  t+1 RTH open ± 1 tick slippage; exit = session t+1+hold RTH close ∓ 1
  tick (market fills both sides, $0.74/side). No intraday stop, no
  target — hold is unconditional (that IS the hypothesis).
- If fewer than hold+1 future sessions exist, no trade. One position at
  a time per arm evaluation (a new signal while holding is ignored).
- r normalization only (no real stop): stop_pts := prior session's RTH
  range, floor 5 pts. Gates read pnl-based metrics as usual.

## Event definition

- mom long: close[t] > max(close[t−N .. t−1]); mom short mirror on the
  N-day closing low. rev = same triggers, opposite direction.
- All N prior sessions must exist (corpus edge sessions skipped).

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| N | 5, 20 (days) |
| hold | 1, 3, 5 (days) |
| arm | mom, rev |

12 grid points. Gates unchanged (session-block bootstrap now blocks by
ENTRY session). sim_version recorded sim-2-daily; FEATURE_VERSION 1
(only OHLC used).

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates** → survivors recorded; one
  validation look spent immediately per standing authority — with the
  research-only label attached: no advisory integration at current
  account size regardless of outcome.
- **No pass** → the daily horizon is efficient too; family CLOSED;
  CYCLE 4 ENDS with the terminal update to HANDOFF.md and the loop
  stops. Ambiguity resolves AGAINST the family.

## Known limitations (accepted at registration)

- No stop means fat left tails are possible; the concentration and
  months gates are the honest referees of that shape.
- Roll-boundary sessions are already excluded by the data layer; hold
  windows spanning a roll use the single owned contract's bars per
  session (price gaps at rolls are real basis, accepted).
- 12 points is deliberately minimal multiplicity for a final probe.
