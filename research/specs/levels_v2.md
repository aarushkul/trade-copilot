# levels_v2 — widened break-event definition (Cycle 3)

Registered blind 2026-07-28. Written from the registered cycle-1/1b verdicts
and the levels-v1 code only. No feature store, bar data, or per-point ledger
results beyond the committed aggregate verdicts were inspected between the
cycle-2 close (2026-07-12) and this spec's commit. The grid below is frozen
at registration; any change is a new spec.

## Provenance and standing

Cycle 1b's registered verdict earmarked exactly one legitimate follow-up:
levels-break — break-through continuation after a first touch approached
from ≥ 5×atr_1m distance — persisted across seven years and three regimes
(PF 2.17, bootstrap-t 2.9, n=68) and failed ONLY the n ≥ 150 gate
(~10 events/yr). The verdict states a wider event definition "would be a
new hypothesis and must be pre-registered blind before anyone looks again."
This is that registration. The fade arms are dropped: the earmark names
break-through continuation as the persistent mechanism; fades are not
carried forward.

## Hypothesis

The v1 break mechanism — a watched reference level approached rapidly from
distance concentrates one-sided stops/liquidity; a decisive, volume-backed
close through it continues — is not specific to prior-day/overnight levels.
If real, it should survive on a wider universe of watched levels (prior
calendar week extremes, 250-pt round numbers, initial-balance extremes) and
at moderately lower approach distances, multiplying event count enough to
clear n ≥ 150 without diluting PF below the gates. If the widened universe
dilutes the edge away, the narrow v1 pattern is scale-specific dust and the
family closes.

## Event definition

Per session, per level L in the chosen levelset, with dist_t = close_t − L
(points, full-session bar array, feature alignment identical to v1):

1. **Touch events** = sign flips of dist (prev and current sign both finite
   and nonzero, signs differ), in chronological order. origin = sign before
   the flip (−1 = approached from below). For IB levels only, flips at bars
   before 10:30 ET are not touch events (the level forms 09:30–10:29).
2. **Touch budget**: examine at most `touch_n` touch events per level per
   session, in order. A touch with index i < 30 (no approach lookback)
   consumes budget and fails. At most ONE signal per level per session;
   a confirmed signal stops further examination of that level.
3. **Approach filter** (unchanged from v1): |dist[i−30]| ≥ approach ×
   atr_1m[i−30], both finite. APPROACH_BARS = 30 fixed.
4. **Break confirmation** (unchanged from v1): first bar j in [i, i+15]
   with sign(dist[j]) = −origin, |dist[j]| ≥ arm_frac × atr_5m[j], and
   rvol_1m[j] ≥ 1.2. Signal direction = −origin (continuation through).
   BREAK_SEARCH_BARS = 15, rvol floor 1.2, both fixed.
5. **Stop** = |dist[j]| + stop_s × atr_5m[j], engine clamp 5–45 pts
   (> 45 kills the signal). Same-bar multi-level signals merge with min
   stop (v1 semantics). Target = target_r × stop. Horizon 60 min. Window
   gates the entry bar. All sim-1 semantics unchanged.

## Level definitions

- **pdh/pdl/pdc/onh/onl** — from feature-store v1 columns exactly as
  levels-v1 (dist reconstructed in points via atr_5m).
- **pwh/pwl** — prior ISO calendar week's max(high)/min(low) over that
  week's sessions present in the loaded split, full-session bars. Sessions
  whose prior ISO week has no sessions in the split (corpus edge, or the
  first validation week when run on validation) carry no PW levels; the
  forgone events are accepted and recorded here, not patched later.
- **rn** — every multiple of 250 index points lying within the session's
  traded range. Enumerating candidates from the realized range is an
  implementation shortcut only: each level is a constant, and touch,
  approach, and confirmation reference bars ≤ signal bar exclusively, so
  no forward information reaches any signal.
- **ibh/ibl** — max(high)/min(low) over bars 09:30–10:29 ET; touch events
  counted from 10:30 ET onward. Sessions without a complete IB window
  (short holiday sessions) carry no IB levels.

## Frozen grid (axes ordered for the ±1-neighbor plateau rule)

| axis | values |
|---|---|
| levelset | daily → weekly → round → full (nested: daily = {pdh,pdl,pdc,onh,onl}; weekly = +{pwh,pwl}; round = +{rn}; full = +{ibh,ibl}) |
| approach | 2.5, 5.0, 10.0 (× atr_1m) |
| arm | break25, break50 (close-through ≥ 0.25 / 0.50 × atr_5m) |
| touch_n | 1, 2 |
| window | rth, w2, w1 (nested 09:30–15:45 ⊃ 10:30–15:00 ⊃ 11:00–14:00) |
| stop_s | 0.5, 1.0 |
| target_r | 1.0, 2.0 |

576 grid points. Gates, sim-1, stats, FEATURE_VERSION (=1): all unchanged.
touch_n = 1 with levelset = daily reproduces v1 "all"-set break semantics.

## Pre-committed readings of the outcome (written before any result)

- **≥ 1 point passes all train gates** → top-2 non-adjacent survivors; one
  validation look is spent immediately under the 2026-07-28 user authority.
- **Best points reach n ≥ 150 but fail PF / bootstrap-t / concentration /
  plateau** → widening dilutes: the v1 pattern is scale-specific or dust.
  Family CLOSED for cycle 3. No sub-gate cherry-picking.
- **Best points still fail only n ≥ 150** → the event class is irreducibly
  rare at this timescale; family CLOSED; revisit ≈ mid-2027 when the tape
  has doubled the v1 event count, per the cycle-1 verdict.
- Any mixed outcome resolves to the nearest reading above; ambiguity is
  scored AGAINST the family.

## Known limitations (accepted at registration)

- 250-pt round increments span a ~7k→24k price era; their relative salience
  drifts. A %-scaled increment would be a NEW spec; not this one.
- IB levels share territory with the dead orb family, but the event here —
  approach-from-distance touch after formation — is not the opening
  breakout; orb's verdict is not evidence either way and is not consulted.
- PW levels near split edges are computed only from in-split sessions
  (guarded loaders make cross-split reads structurally hard); missing-week
  events are forgone, never backfilled.
