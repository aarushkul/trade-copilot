# Cycle 4 — event_day and vol_regime verdicts (2026-07-29)

## event_day — 0/144, family CLOSED

Run `r-20260729-012938-b75cc4c6`, calendar frozen with provenance (55
scheduled FOMC + 81 CPI + 81 NFP; unscheduled FOMC excluded; Q4-2025 BLS
truncated). Best: cpi_nfp FOLLOW at delay 1 — PF 1.9–2.0 on n=63–80,
t 1.4–1.7, months + top10 fail. Scarcity is structural: thin 2019–2020
pre-markets drop many 08:29 anchor bars, halving usable events. The
scheduled-event reaction is the same lottery, smaller. CLOSED per
pre-commitment; the follow-vs-fade asymmetry (follow >> fade at short
delay) is recorded as information only.

## vol_regime — 0/24, family CLOSED, and the trend_harvest revival dies with it

Run `r-20260729-013536-5eca29ed`. (Spec text says "48 grid points" — an
arithmetic typo; the frozen AXES table and the registered PARAMS_GRID
hash enumerate exactly the 24 points run: 2 N × 2 trail_k × 2 vol_k ×
3 cond.)

The result INVERTS the hypothesis: the best point is the pre-registered
FALSIFICATION arm — low-vol — at PF 1.26, n=828, t 2.1 (fails months +
top10; the high arm's best is PF 1.19 at t 1.1). Breakout-trail drift is
mildly better in QUIET regimes (less whipsaw), the opposite of the
high-vol-concentration thesis, and still lottery-shaped everywhere. Per
the double-kill pre-commitment: vol-state conditioning is dead AND the
trend_harvest revival door is permanently closed on this corpus. The VX
skip (cost cap) is documented in the spec.

## Standing

Cycle-4 slate remaining: overnight Globex structure, daily_swing
(research-only). Program lifetime: 24 pre-registered runs, 3,645
evaluated configurations, zero survivors. All looks and the holdout
remain unspent.
