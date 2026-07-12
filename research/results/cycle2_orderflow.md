# Cycle 2 results — order flow (NQ tick-rule proxy, 2025 train year)

Date: 2026-07-12 (overnight). Runs `r-20260712-022127` (orderflow rules) +
the ml-v2-flow run. Data: $53.08 of free credits (NQ ohlcv-1s 2025-01-01 →
2025-12-10 + one month of true NQ trades for proxy validation). 241
flow-covered train sessions.

## Verdict: 0/72 pass — SCOPED as "proxy too weak", per pre-registration

| checkpoint | result |
|---|---|
| side-convention decode | PASS — true delta vs MNQ 1m return corr +0.686 |
| proxy sanity by quarter | PASS — proxy delta vs return +0.63..+0.69 all quarters |
| **proxy credibility gate (>= 0.8)** | **FAIL — corr(proxy, true delta) = 0.706** |
| supplementary: rolled windows | 5m imbalance 0.736, 15m 0.763 — still < 0.8 |
| orderflow rule grids (40 pts) | 0 pass; best PF 1.12, n=64, t=0.4 |
| ml-v2 (v1+flow features, 32 pts) | 0 pass; best PF 1.06 vs ml-v1's 0.98 |

## What this does and does not establish

- The infrastructure decodes real aggressor flow correctly (the true-trades
  month behaves exactly as the literature says: +0.69 contemporaneous
  correlation with returns).
- The AFFORDABLE flow signal — a tick-rule reconstruction from 1s bars —
  is a ~0.71-fidelity shadow of real flow, and nothing built on it clears
  costs. Rolling to 5m/15m does not lift fidelity past the bar we set.
- Per the pre-pull addendum, this cycle therefore does **not** prove
  "order flow is dead"; it proves "order flow cannot be tested honestly at
  this budget." The distinction is registered and binding.

## What a real test would cost

True NQ trades for the 2025 train year: ~$122. Remaining free credits:
~$62. A half-year (~$61) would fit but guts the months-positive and n
gates. So a full-fidelity order-flow cycle requires ~$60-120 of actual
money — a user decision, explicitly NOT taken autonomously. The staged
rule stands: no validation look may be considered on flow results until
a full-fidelity train pass exists.

## Program totals after cycle 2

1,592 registered evaluations across three cycles. Zero survivors. All
validation looks and the single holdout look remain unspent.
