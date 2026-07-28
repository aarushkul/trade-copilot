# compression — coil breakout, optionally NR-day conditioned (Cycle 3)

Registered blind 2026-07-28, before any evaluation. Written from code and
registered verdicts only; no bar data or feature values inspected. Grid
frozen at registration; any change is a new spec. First registration of
this family.

## Hypothesis

Range compression precedes directional expansion. An intraday coil — an
m-bar trailing range unusually tight versus current volatility — resolves
with follow-through in the break direction; conditioning on a narrow-range
prior session (NR-k) concentrates the effect. If no arm clears the gates,
compression is decoration on MNQ 1m at these costs and the family closes.

Relation to dead families, pre-noted: orb died as an UNCONDITIONAL opening
breakout; trend_continuation died as pullback-in-trend. The event here is a
volatility-conditioned coil break anywhere in the window, plus a day-level
conditioner neither family had. Their verdicts are not evidence either way.

## Event definition

At bar t (closed-bar evaluation, sim-1 enters next bar):

- coil = max(high) − min(low) over bars [t−m, t−1] (m full bars, t
  excluded). Valid only when all bars exist (t ≥ m).
- Compressed iff coil ≤ c × atr_5m[t].
- Breakout: close[t] > coilmax + b × atr_1m[t] (long) or close[t] <
  coilmin − b × atr_1m[t] (short), with rvol_1m[t] ≥ 1.2.
- NR-k conditioner (axis value none = off): the session qualifies iff the
  PRIOR session's RTH range (09:30–15:59 high−low) is the narrowest of the
  last k prior sessions' RTH ranges (strictly earlier sessions only,
  computed within the loaded split; corpus-edge sessions without k prior
  sessions do not qualify).
- Re-arm: after a signal, no further signals for m bars (same session).
- Stop = (close[t] − coilmin) + stop_s × atr_5m[t] for longs (mirror for
  shorts) — structural: the other side of the coil plus buffer. Engine
  clamp 5–45 pts. Target = target_r × stop. Horizon 60 min fixed.

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| nr_k | none, 4, 7 |
| m | 20, 40 (bars) |
| c | 1.5, 2.0, 3.0 (× atr_5m) |
| break_b | 0.0, 0.5 (× atr_1m) |
| window | rth, w2 |
| stop_s | 0.5, 1.0 (× atr_5m) |
| target_r | 1.0, 2.0 |

288 grid points. Gates, sim-1, FEATURE_VERSION (=1): unchanged.

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates** → top-2 non-adjacent survivors; one
  validation look spent immediately under the 2026-07-28 user authority.
- **No pass** → family CLOSED for cycle 3; no re-grid, no loosened
  variant, regardless of near-misses. Ambiguity resolves AGAINST the
  family.

## Known limitations (accepted at registration)

- The NR-k conditioner uses only in-split prior sessions (guarded loaders);
  split-edge sessions forgo the conditioner rather than peek across.
- c thresholds couple m and atr_5m without a √time correction — chosen
  blind for simplicity; a normalized variant would be a new spec.
- Multiple coils per session are allowed (re-arm after m bars); the
  concentration gate polices any resulting clustering.
