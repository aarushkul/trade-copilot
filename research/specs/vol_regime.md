# vol_regime — ES-realized-vol conditioning of the trend drift (Cycle 4)

Registered blind 2026-07-29, before any evaluation. Grid frozen at
registration; any change is a new spec. Cycle-4 family 2.

VX/implied-vol note, per the slate's cost pre-commitment: XCBF VX daily
quotes at $81.64 (> $15 cap; per-contract symbology unresolvable via free
metadata), so implied vol is SKIPPED and the conditioner is ES realized
vol from the owned train-only ES corpus — external to the MNQ series,
zero cost. This substitution was decided before any evaluation.

## Hypothesis

The trend_harvest drift (the only genuine drift measured; PF 1.20 on
n=1,692 lifetime, lottery-shaped) is not uniform across volatility
states. An EXTERNAL vol-state conditioner concentrates it into
high-vol regimes strongly enough to clear ALL gates including top-10
concentration — or vol states carry no conditioning information, and
BOTH this family and the trend_harvest revival die together.

## Winner's-curse guardrails (stated before results)

- The base entries are a FROZEN 2×2 BLOCK of the drift region — N ∈
  {30, 60} × trail_k ∈ {3.0, 4.0} — not the single best cycle-3 point.
  Base selection uses registered aggregates only (allowed); the
  conditioner must clear gates somewhere in the block whose ±1
  neighbors also behave (plateau rule as usual).
- Remaining base axes are fixed a priori, with reasons: filt=none
  (simplest), rvol_f=1.0 (loosest → most events for the conditioner to
  work with), init_stop_s=2.0 (wide initial stop suits trend riding),
  entries_cap=1, window=rth.
- A pass on the low-vol arm alone — contradicting the thesis — counts
  as FAILURE (sign-flip cherry-picking guard). Ambiguity resolves
  AGAINST the family.

## Conditioner definition (strictly causal, external data)

- Per ES session (owned xmkt_ES* files, train window): Parkinson-style
  realized vol = sqrt(mean(ln(high/low)²)) over RTH minute bars
  (570–959, bars with high > low > 0).
- Measure = mean of that RV over the prior k ES sessions (k axis),
  LAGGED ONE FULL SESSION (the state trading session t uses sessions
  ≤ t−1 only).
- State = percentile of the measure within its trailing 252-ES-session
  window (expanding until 252 exist; sessions with < 60 trailing ES
  sessions have no state and produce no signals).
- cond axis: high = trade only percentile ≥ 2/3; midhigh = trade
  percentile ≥ 1/3; low = trade only percentile < 1/3 (the
  falsification arm).
- MNQ sessions with no ES session or no state → no signals (never
  patched).

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| N | 30, 60 |
| trail_k | 3.0, 4.0 |
| vol_k | 5, 20 (sessions) |
| cond | low, midhigh, high |

48 grid points. Entries/exits exactly as trend_harvest (sim-1.1,
breakout through the N-bar extreme, stop = through-level + 2.0×atr_5m,
trail = trail_k×atr_5m frozen at signal, cap 1/side/session, rth
window). Gates unchanged; sim_version sim-1.1; FEATURE_VERSION 1.

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates on the high or midhigh arm** →
  top-2 non-adjacent survivors; one validation look spent immediately.
  Spending it REQUIRES pulling the validation-window ES slice at that
  moment (small, quoted, part of the look) to compute states.
- **No pass (or only the low arm passes)** → vol-state conditioning is
  dead AND the trend_harvest revival is dead with it. No re-grid.
- Cycle 4 then continues to the overnight family regardless.

## Known limitations (accepted at registration)

- Realized vol ≠ implied; a VX-based version would be a new spec if the
  data economics ever change.
- Parkinson RV from 1m bars underestimates gap risk; accepted for
  ranking states, not levels.
- Conditioning a closed family's entries is revival-by-new-information;
  this spec is the ONE such attempt permitted by the cycle-4 mandate,
  and its failure closes both doors permanently on this corpus.
