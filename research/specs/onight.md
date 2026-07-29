# onight — overnight-range breakout in the European window (Cycle 4)

Registered blind 2026-07-29, before any evaluation. Grid frozen at
registration; any change is a new spec. Cycle-4 family 3. First family
to trade outside RTH: a new "eu" entry window (02:00–08:00 ET) is added
to the harness (WINDOWS), committed before registration.

## Hypothesis

Every family so far entered 09:30–15:45; the overnight Globex session is
untouched territory in data we already own. The European hours are when
the ON range first breaks with real participation: a decisive,
volume-backed break of the accumulated 18:00–01:59 range during
02:00–08:00 ET carries follow-through (ridden with a sim-1.1 trail into
the US day, force-flat 15:59) — or overnight structure is noise at these
costs and the family closes.

Practicality pre-noted: even a pass yields calls at hours the user does
not trade; the value would be session-context/knowledge first.

## Event definition (closed bars; sim-1.1; one signal per side per session)

- ON range: max(high)/min(low) over bars with minute_et ≥ 1080 or
  < 120 (18:00–01:59 ET); requires ≥ 180 such bars, else no events.
- Breakout at bar t in the eu window (120 ≤ minute_et ≤ 480): close[t] >
  onh + b × atr_1m[t] (long; mirror below onl), rvol_1m[t] ≥ 1.2.
  First qualifying bar per side only (cap 1/side).
- Stop = (close[t] − onh) + stop_s × atr_5m[t] for longs (back through
  the broken level + buffer; mirror shorts), clamp 5–45 pts.
- Trail = trail_k × atr_5m[t] frozen at signal; ride to force-flat
  15:59 (a position opened at 03:00 may ride ~13 hours — intended).

## Frozen grid (axes ordered for the plateau rule)

| axis | values |
|---|---|
| b | 0.0, 0.5 (× atr_1m) |
| stop_s | 1.0, 2.0 (× atr_5m) |
| trail_k | 2.0, 3.0 (× atr_5m) |

8 grid points (deliberately minimal multiplicity). Gates unchanged;
sim_version sim-1.1; FEATURE_VERSION 1; window "eu" fixed.

## Pre-committed readings of the outcome

- **≥ 1 point passes all train gates** → top-2 non-adjacent survivors;
  one validation look spent immediately — WITH the mandatory overnight
  liquidity caveat attached (see limitations): paper phase must verify
  fill quality before any advisory use.
- **No pass** → overnight structure is noise at these costs; family
  CLOSED; cycle 4 proceeds to daily_swing. Ambiguity resolves AGAINST.

## Known limitations (accepted at registration)

- sim-1's 1-tick slippage understates overnight spreads/liquidity,
  especially 2019–2020 MNQ; the 1.5× stress gate matters more here and
  a pass still carries a mandatory liquidity caveat.
- Thin overnight sessions naturally produce missing bars and smaller n;
  events are forgone, never patched.
- The in-family ON range (cut at 01:59) deliberately differs from the
  feature store's onh/onl (full overnight); the family computes its own.
