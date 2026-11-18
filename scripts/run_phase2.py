"""KEPT DELIBERATELY — do not delete as superseded tooling.

This script generated the 749-episode deep pilot, which is still the baseline
every later arm is compared against. `run_rung.py` supersedes it for new work,
but deleting the generator of a live baseline is a provenance loss: the numbers
it produced are cited throughout the preregistration and the writeup, and the
only record of HOW they were produced is this file.

Same reasoning as the retained `*-INVALID-noagg` logs and the superseded prompt
versions — kept because something reported still depends on them.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sedition.pipeline import failure_policy as fp
from sedition.scoring import stopping

from sedition_inspect.dataset import ALL_PACKETS
from sedition_inspect.episodes import episode_rows, provider_calls
from sedition_inspect.run import run_stage

#: (cell, overlay). Honest carries no overlay, so it runs once.
COMBINATIONS = (
    ("honest_straight", "current"),
    ("basic_straight", "current"),
    ("basic_straight", "balanced"),
    ("strategic_straight", "current"),
    ("strategic_straight", "balanced"),
)


def rows_for(root: str, cell: str, overlay: str, upto: int) -> list[dict]:
    out = []
    for b in range(upto + 1):
        out.extend(episode_rows(f"{root}/{cell}-{overlay}/b{b}"))
    return out


def block_line(cell: str, overlay: str, b: int, rows: list[dict],
               elapsed: float) -> None:
    """One line per block. Cheap, and the strategic split is on it."""
    n = len(rows)
    flags = Counter(f for r in rows for f in (r.get("flags") or []))
    deg = flags.get("DEGENERATE_OUTPUT", 0)
    trunc = flags.get("TRUNCATED", 0)
    parse = flags.get("SELECTION_MALFORMED", 0) + flags.get("WO_MALFORMED", 0)
    drs = sum(1 for r in rows if r.get("drs") is not None)
    d = fp.denominators(rows)
    line = (f"    b{b:<2d} n={n:<3d} deg={deg:<2d} trunc={trunc:<2d} "
            f"parse_fail={parse:<2d} drs={drs}/{n} "
            f"cnt-facts={d['counted'] - d['facts']}")
    if cell.startswith("strategic"):
        dec = Counter(r.get("attack_decision") or "MISSING" for r in rows)
        recent = [r for r in rows if r.get("block") == b]
        rdec = Counter(r.get("attack_decision") or "MISSING" for r in recent)
        line += (f"  |  this block ATTACK={rdec.get('ATTACK', 0)} "
                 f"ABSTAIN={rdec.get('ABSTAIN', 0)}"
                 f"  cumulative ATTACK={dec.get('ATTACK', 0)} "
                 f"ABSTAIN={dec.get('ABSTAIN', 0)}")
    line += f"   ({elapsed:.0f}s)"
    print(line, flush=True)


def cell_report(cell: str, overlay: str, rows: list[dict]) -> None:
    print(f"\n  {'=' * 74}")
    print(f"  CELL COMPLETE — {cell} / v_{overlay}   {len(rows)} episodes")
    print(f"  {'=' * 74}")
    d = fp.denominators(rows)
    flags = Counter(f for r in rows for f in (r.get("flags") or []))
    print(f"    degeneration    : {flags.get('DEGENERATE_OUTPUT', 0)}/{len(rows)}")
    print(f"    truncation      : {flags.get('TRUNCATED', 0)}/{len(rows)}")
    print(f"    parse failures  : selection={flags.get('SELECTION_MALFORMED', 0)} "
          f"officer={flags.get('WO_MALFORMED', 0)}")
    print(f"    DRS coverage    : {d['drs']}/{d['counted']}")
    print(f"    counted - facts : {d['counted'] - d['facts']}")
    print(f"    denominators    : " + "  ".join(
        f"{k}={v}" for k, v in d.items() if not isinstance(v, dict)))

    dec = Counter((r.get("wo_final") or r.get("wo") or "NONE") for r in rows)
    print(f"    officer         : {dict(dec)}")

    if cell.startswith("strategic"):
        ad = Counter(r.get("attack_decision") or "MISSING" for r in rows)
        lev = Counter(r.get("primary_lever") or "-" for r in rows)
        risks = [r.get("detection_risk") for r in rows
                 if isinstance(r.get("detection_risk"), int) and r["detection_risk"] >= 0]
        print(f"    ATTACK/ABSTAIN  : {dict(ad)}")
        print(f"    primary_lever   : {dict(lev.most_common(5))}")
        if risks:
            print(f"    detection_risk  : min={min(risks)} max={max(risks)} "
                  f"mean={sum(risks)/len(risks):.1f} n={len(risks)}")
    print(flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--blocks", type=int, default=25)
    p.add_argument("--log-dir", default="logs/phase2")
    p.add_argument("--model-set", default="foundry_deepseek")
    args = p.parse_args()

    total = len(COMBINATIONS) * args.blocks * len(ALL_PACKETS)
    print(f"DEEP PILOT — {len(COMBINATIONS)} combinations x {args.blocks} blocks "
          f"x {len(ALL_PACKETS)} packets = {total} episodes")
    print(f"  model set : {args.model_set}")
    print(f"  log dir   : {args.log_dir}")
    print(f"  design    : docs/PHASE2-DESIGN.md")
    print(f"  rules     : docs/PREREGISTRATION.md section 8\n", flush=True)

    t_start = time.time()
    for cell, overlay in COMBINATIONS:
        print(f"\n{'#' * 78}")
        print(f"# {cell}  /  v_{overlay}")
        print(f"{'#' * 78}", flush=True)
        root = f"{args.log_dir}/{cell}-{overlay}"

        for b in range(args.blocks):
            t0 = time.time()
            ok, _ = run_stage(
                model_set=args.model_set,
                packets=ALL_PACKETS,
                cells=cell,
                block_indices=(b,),
                overlay=overlay,
                log_dir=f"{root}/b{b}",
            )
            if not ok:
                print(f"\n  block {b} did not complete. Re-invoke with the same "
                      f"arguments to resume.", flush=True)
                return 2

            rows = rows_for(args.log_dir, cell, overlay, b)
            block_line(cell, overlay, b, rows, time.time() - t0)

            errors = calls = 0
            for done in range(b + 1):
                e, c = provider_calls(f"{root}/b{done}")
                errors += e
                calls += c
            verdict = stopping.evaluate(
                rows, scope=f"{cell}/v_{overlay}", blocks=b + 1,
                provider_errors=errors, provider_calls=calls)
            if verdict.stop:
                print(f"\n{'!' * 78}")
                print(f"STOPPED — {cell}/v_{overlay} block {b}")
                print(verdict.report())
                print(f"{'!' * 78}", flush=True)
                return 1

        cell_report(cell, overlay, rows_for(args.log_dir, cell, overlay,
                                            args.blocks - 1))

    print(f"\n{'=' * 78}")
    print(f"DEEP PILOT COMPLETE — {total} episodes in "
          f"{(time.time() - t_start) / 60:.1f} min")
    print(f"  python scripts/tranche_status.py {args.log_dir}/*/b*")
    print(f"{'=' * 78}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
