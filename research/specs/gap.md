# gap — overnight-gap fade/continuation at the RTH open (Cycle 3)

Registered blind 2026-07-28, before any evaluation. Written from code and
registered verdicts only; no bar data or feature values inspected. Grid
frozen at registration; any change is a new spec. First registration of
this family (it was not in the cycle-1 slate).

## Hypothesis

The overnight gap — prior-RTH-close displacement at the 09:30 open — is the
one piece of session-scale information the dead families never used as a
primary conditioner. Classic structure: moderate gaps mean-revert toward
the prior close (fade), large gaps continue away from it (go). If neither
arm clears the gates net of costs, gaps carry no tradeable edge on MNQ 1m
and the family closes.

Context pre-noted: the cycle-1 tod study measured unconditional 09:30-10:00
entries as the worst bucket (−0.13 R drag). This family's entries live
exactly there, so the conditioning must beat that drag — that is the test,
not an excuse. The regime family's "gap" day-type detector failing is not
evidence here (different question: classification freeze vs a trade rule).

## Event definition (one candidate entry per session per grid point)

- open_bar = first bar with minute_et ≥ 570 (09:30 ET).
- gap = pdc_dist_atr[open_bar] — the first RTH bar's close vs prior RTH
  close, in atr_5m units (feature-store column, causal). Not finite → no
  event (first session of corpus).
- Size filter: gmin ≤ |gap| ≤ gcap (gcap 999 = uncapped arm).
- entry_bar = open_bar + delay (bars). Signal fires on entry_bar (closed
  bar; sim-1 enters next bar open) iff the gap is still ≥ half unfilled:
  sign(pdc_dist_atr[entry_bar]) = sign(gap) AND |pdc_dist_atr[entry_bar]|
  ≥ 0.5 × |gap|. The 0.5 floor is a fixed constant, chosen blind.
- Direction: fade = toward prior close (−sign(gap)); go = with the gap
  (+sign(gap)).
- Stop = stop_s × atr_5m[entry_bar] (ATR stop, not structural — stated
  choice), engine clamp 5–45 pts. Target = target_r × stop. Window fixed
  "rth". At most one signal per session.

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| gmin | 0.5, 1.0, 2.0 (× atr_5m) |
| gcap | 4.0, 999 |
| arm | fade, go |
| delay | 1, 15, 30 (bars after open) |
| stop_s | 1.0, 2.0 (× atr_5m) |
| target_r | 1.0, 2.0 |
| horizon | 60, 120 (min) |

288 grid points. Gates, sim-1, FEATURE_VERSION (=1): unchanged. n ≥ 150 is
reachable (most sessions gap ≥ 0.5 × atr_5m), so this family lives or dies
on PF / bootstrap-t / concentration, not scarcity.

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates** → top-2 non-adjacent survivors; one
  validation look spent immediately under the 2026-07-28 user authority.
- **No pass** → gaps are decoration on MNQ 1m at these costs; family
  CLOSED for cycle 3; the fade-vs-go asymmetry is recorded for the ledger
  but earns no re-grid and no loosened variant.
- Ambiguity resolves AGAINST the family.

## Known limitations (accepted at registration)

- Fixed-R targets stand in for literal gap-fill targets (sim-1 supports R
  multiples only). A fill-target variant would be a new spec plus a sim
  extension — not this one.
- delay is the only timing lever; the window stays "rth". No post-hoc
  window rescue if the open drag dominates.
- The 0.5 unfilled floor and the 999 uncapped sentinel are fixed blind.
