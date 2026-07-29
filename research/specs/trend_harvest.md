# trend_harvest — breakout entries under uncapped trailing exits (Cycle 3)

Registered blind 2026-07-29, before any evaluation. Grid frozen at
registration; any change is a new spec. First registration of this family
and of fill model **sim-1.1** (defined below; sim-1 untouched and all
prior registrations stand).

## Hypothesis

The cycle-3 meta-finding (recorded 2026-07-28, before this spec): MNQ 1m
P&L net of costs = a breakeven base plus rare trend-day outliers, across
four event archetypes. Every family so far capped exits at 1–2R with
≤120m horizons — structurally unable to hold a 200–400-pt trend leg.
Hypothesis: session-range breakout entries are ~free (orb died flat, not
negative), and the missing edge is in the EXIT — an uncapped ATR trailing
stop that rides trend legs to force-flat converts the outlier days into
enough medium-sized wins to pass ALL gates, including top-10
concentration (spread across the ~dozens of trend legs per year, not 10
trades). If no point passes, the exit-structure hypothesis is dead and
cycle 3 ends with the honest terminal report.

Prior evidence cited against, for honesty: the 2026-07-09 in-sample
scalp-vs-homerun study measured a 6R/240m arm ≈ baseline for the OLD
engine's confluence entries; gap's 60↔120m horizon axis barely mattered.
Neither tested uncapped trails on breakout entries; the prior is modest.

## sim-1.1 (trailing-exit fill model; versioned, golden-tested)

Everything from sim-1 holds (closed-bar signals, next-bar-open entry ±1
tick, stops are market fills paying slippage, force-flat 15:59 ET, one
position at a time, $0.74/side) except the exit:

- No profit target. Exit is stop-only: effective_stop(j) =
  max(initial_stop, trail(j)) for longs (min for shorts), a monotone
  ratchet.
- trail(j) = post-entry extreme of PRIOR CLOSED bars (highs for longs,
  from the entry bar onward) − trail_pts; trail_pts is FROZEN at the
  signal bar (trail_k × atr_5m[signal]). On the entry bar itself only the
  initial stop is active (no prior closed post-entry bar exists).
- Fill: if the bar opens through the effective stop, fill at open − slip
  (gap-through); else at stop level − slip. Exit reasons: STOP (initial),
  TRAIL (ratcheted), FLAT (15:59 / session end). No target ⇒ sim-1's
  stop/target ambiguity rule is vacuous; the ratchet uses prior bars only
  ⇒ no same-bar ratchet-then-hit ambiguity.
- Golden hand-tape tests are part of this registration (ride+pullback
  exit, gap-through, entry-bar initial stop, EOD flat, short mirror,
  cost arithmetic to the cent).

## Event definition

- Breakout long at bar t (RTH bars 570–945 only): close[t] >
  max(high[t−N .. t−1]) with all N prior bars present (t ≥ N), rvol_1m[t]
  ≥ rvol_f, and (filt=ema only) ema21_5m_dist_atr[t] > 0. Shorts mirror
  on the N-bar low with dist < 0.
- Per side: emitted signals re-arm after N/2 bars; at most entries_cap
  emitted signals per side per session. (The sim's one-position rule then
  takes the tradeable subset — signals during an open position are
  consumed by nothing.)
- Initial stop = (close[t] − N-bar-high) + init_stop_s × atr_5m[t] for
  longs (structural: back through the broken level plus buffer), mirror
  for shorts; engine clamp 5–45 pts. Horizon: none (ride to force-flat).

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| N | 30, 60, 120 (bars) |
| filt | none, ema |
| rvol_f | 1.0, 1.5 |
| trail_k | 2.0, 3.0, 4.0 (× atr_5m at signal) |
| init_stop_s | 1.0, 2.0 (× atr_5m) |
| entries_cap | 1, 2 (per side per session) |
| window | rth, w2 |

288 grid points. Gates and FEATURE_VERSION (=1) unchanged; sim_version
recorded as sim-1.1 in the registration.

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates** → top-2 non-adjacent survivors;
  one validation look spent immediately under the 2026-07-28 authority.
- **No pass, and top10 concentration is still the binding failure** →
  trend-day P&L cannot be spread by exit design; the outlier structure is
  irreducible at 1m; CYCLE 3 ENDS with the terminal report.
- **No pass on PF/t (trails give it back in chop)** → same ending, cause
  recorded as whipsaw cost, not concentration.
- Ambiguity resolves AGAINST the family. No re-grid.

## Known limitations (accepted at registration)

- trail_pts frozen at signal (no ATR re-scaling mid-trade) — chosen blind
  for determinism.
- Breakout scan uses session arrays including overnight bars for the
  N-bar extreme (a 09:40 breakout can break an overnight high) — that IS
  the intended "session range" for this spec.
- sim-1.1 parity vs replay.py is not claimed (replay has no trail mode);
  the golden tapes are the verification, per the harness clause.
