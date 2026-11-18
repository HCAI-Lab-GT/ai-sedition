"""Run one ladder rung or prompt-version arm, block by block.

    python scripts/run_rung.py v8-free
    python scripts/run_rung.py rungN --blocks 50

One `run_stage` call per block, because `eval_set` resumes on task identity:
a single call spanning 50 blocks that dies at block 40 cannot resume, while
50 single-block calls each own their own log directory and the finished ones
are simply not re-run.

Every arm is its own log directory. Nothing pools across prompt versions, so
keeping v6/v8/v9 in separate trees is what makes accidental pooling a missing
directory rather than a silent averaging.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sedition_inspect.run import run_stage

PACKETS = ("E02-MS", "E03-MS")

#: name -> kwargs for run_stage. `overlay` selects the prompt VERSION arm;
#: the rung flags are additive scaffolding on top of whichever version is set.
ARMS: dict[str, dict] = {
    # --- prompt-version arms ------------------------------------------------
    "v8-free":     dict(overlay="permissive", selection_mode="free"),
    "v8-forced":   dict(overlay="permissive", selection_mode="forced"),
    "v9-free":     dict(overlay="gist", selection_mode="free"),
    "v9-forced":   dict(overlay="gist", selection_mode="forced"),
    # --- elicitation rungs, on v8 unless stated -----------------------------
    "rung25":      dict(selection_mode="forced", observed_behaviour=True),
    "rungN":       dict(overlay="permissive", selection_mode="free", best_of=8),
    "rung6":       dict(overlay="permissive", selection_mode="free",
                        proxy_iterations=3),
    "rung2":       dict(overlay="permissive", selection_mode="forced",
                        self_critique=True),
    "rung1xB":     dict(overlay="balanced", selection_mode="forced"),
    # --- rung 7: aggregation, the one dimension 8 rungs never moved ---------
    "rung7":       dict(overlay="permissive", selection_mode="free",
                        aggregation=True),
    "rung7xN":     dict(overlay="permissive", selection_mode="free",
                        aggregation=True, best_of=8),
    "rung7c":      dict(overlay="permissive", selection_mode="free",
                        aggregation=True, aggregation_full_form=True),
    "rung7d":      dict(overlay="permissive", selection_mode="free",
                        aggregation=True, aggregation_full_form=True,
                        aggregation_shape=True),
    # --- deceptive arm: honesty released for the target only ----------------
    "decep-free":   dict(overlay="deceptive", selection_mode="free"),
    "decep-forced": dict(overlay="deceptive", selection_mode="forced"),
    # --- v11: the licence stated affirmatively and the contradictions removed
    "v11-forced":   dict(overlay="unconstrained", selection_mode="forced"),
    "v11-free":     dict(overlay="unconstrained", selection_mode="free"),
    # --- quarantined --------------------------------------------------------
    "rung4":       dict(overlay="permissive", selection_mode="forced",
                        disclosed_mechanism=True),
    "rung4xAgg":   dict(overlay="permissive", selection_mode="forced",
                        disclosed_mechanism=True, aggregation=True),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=sorted(ARMS))
    ap.add_argument("--blocks", type=int, default=50)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--log-dir", default="")
    args = ap.parse_args()

    kwargs = ARMS[args.arm]
    root = args.log_dir or f"logs/{args.arm}"
    print(f"{args.arm}: {kwargs}", flush=True)
    print(f"log root: {root}   blocks {args.start}..{args.blocks - 1}", flush=True)

    failed = 0
    for b in range(args.start, args.blocks):
        ok, _ = run_stage(
            model_set="foundry_deepseek", packets=PACKETS,
            cells="strategic_straight", block_indices=(b,),
            log_dir=f"{root}/b{b}", **kwargs,
        )
        print(f"block {b}: {'ok' if ok else 'FAILED'}", flush=True)
        # One bad block is not a reason to abandon the arm — the failure
        # policy aborts on RATES, not on a single event, and the finished
        # blocks are already durable on disk.
        failed += 0 if ok else 1
        if failed >= 5:
            print(f"ABORTING {args.arm}: 5 failed blocks", flush=True)
            return 1
    print(f"{args.arm.upper()} COMPLETE ({failed} failed blocks)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
