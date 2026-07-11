"""Register and run one research family study.

Usage:
    .venv/bin/python scripts/research/run_family.py --family regime
    .venv/bin/python scripts/research/run_family.py --family tod

Registration hits the ledger BEFORE any evaluation (research/README.md).
Train runs are unlimited; validation/holdout consume the look budget.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.research import families, ledger  # noqa: E402
from app.research.features import FEATURE_VERSION, load_features  # noqa: E402
from app.research.sim import SIM_VERSION  # noqa: E402
from app.research.splits import data_fingerprint  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True)
    ap.add_argument("--split", default="train")
    args = ap.parse_args()

    mod = families.get(args.family)
    feats = load_features(args.split) if args.split == "train" else None
    fp = (data_fingerprint(sorted(set(feats["session"])))
          if feats is not None else "n/a")

    spec = {
        "family": mod.FAMILY,
        "spec_id": mod.SPEC_ID,
        "split": args.split,
        "hypothesis": mod.HYPOTHESIS,
        "params_grid": mod.PARAMS_GRID,
        "feature_version": FEATURE_VERSION,
        "sim_version": SIM_VERSION,
        "data_fingerprint": fp,
    }
    run_id = ledger.register(spec)
    print(f"registered {run_id} ({mod.FAMILY} on {args.split})")

    results = mod.run(args.split, run_id)
    for params, metrics, gates in results:
        ledger.append_result(run_id, params, metrics, gates)
    print(f"{len(results)} results appended to ledger\n")

    if hasattr(mod, "report"):
        print(mod.report(results))
    elif hasattr(mod, "AXES"):
        from app.research.families.common import survivors
        passed = [r for r in results if r[2].get("train_pass")]
        print(f"train-gate passers: {len(passed)}/{len(results)}")
        for p, m, _ in sorted(passed, key=lambda r: -r[1].get("expectancy_usd", 0))[:10]:
            print(f"  PASS {json.dumps(p)}")
            print(f"       n={m['n']} pf={m['pf']:.2f} exp=${m['expectancy_usd']:.2f} "
                  f"t={m['bootstrap_t']:.1f} months+={m['months_pos_frac']:.0%} "
                  f"top10={m['top10_share']:.0%} stress_pf={m.get('stress_pf')}")
        surv = survivors(results, mod.AXES)
        print(f"survivors (<=2 non-adjacent): {json.dumps(surv)}")
        best = sorted(results, key=lambda r: -(r[1].get("pf", 0) if r[1].get("n", 0) >= 50 else 0))[:5]
        print("top PF regardless of gates (n>=50):")
        for p, m, g in best:
            print(f"  {json.dumps(p)}")
            print(f"       n={m.get('n')} pf={m.get('pf', 0):.2f} "
                  f"exp=${m.get('expectancy_usd', 0):.2f} t={m.get('bootstrap_t', 0):.1f}"
                  f" failed={','.join(g.get('failed', [])) or '-'}")
    else:
        for params, metrics, gates in results:
            flag = ""
            if gates:
                flag = " PASS" if gates.get("freeze_pass") or gates.get("train_pass") \
                    else f" fail({','.join(gates.get('failed', []))})"
            print(f"{json.dumps(params):60s} {json.dumps(metrics)}{flag}")


if __name__ == "__main__":
    main()
