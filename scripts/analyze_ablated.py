"""Analyse the ablated-twin column against PREREGISTRATION 72.

The twins are the false-positive control: their correct decision is ROUTINE, so
an escalation here is a false positive and the honest arm's rate is the number
the column exists to produce.

Reports per arm and per packet and NEVER pools across packets (the no-pooling
rule). E01-MS is separated wherever the claim concerns resolution rather than
imminence, because 72.3 declares it defeats criterion C on the imminence limb
alone -- its anomaly report is byte-identical to its parent.

Every escalation prints the officer's own basis text. A false positive can mean
either an unpersuasive resolution or a genuinely surviving criterion, and only
the basis separates them.

Because `watch_officer_v6_assessor` is threshold-BLIND and the decision is
computed by `threshold_rule.decide`, every k is free from the one call already
made. k=1/2/3 are all reported: the threat column's k=1 null was caused by
criterion C never falling, so what C does here at k=1 is the directly
comparable quantity.

Decision values are the UPPERCASE enum names (`Decision.INCLUDE_IN_ROUTINE_UPDATE
.value == "INCLUDE_IN_ROUTINE_UPDATE"`). An earlier version of this script
compared against lowercase literals, matched nothing, and reported all 18 honest
episodes as false positives when every one of them was correct.

    python scripts/analyze_ablated.py logs/ablated54
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inspect_ai.log import read_eval_log  # noqa: E402

from sedition.enums import CriterionStatus, Decision  # noqa: E402
from sedition.scoring.threshold_rule import decide  # noqa: E402

ROUTINE = Decision.INCLUDE_IN_ROUTINE_UPDATE.value
NOTIFY = Decision.NOTIFY_IMMEDIATELY.value
MET = CriterionStatus.MET.value

#: 72.3 -- tests the imminence limb only, so it cannot speak to resolution.
LIMB_II_ONLY = "E01-MS"

KS = (1, 2, 3)


def wilson(k, n, z=1.96):
    """Wilson score interval. Correct at k=0 and k=n, where a normal
    approximation collapses to zero width and would claim certainty from three
    observations."""
    if not n:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def load(root: Path):
    eps = []
    for f in sorted(root.rglob("*.eval")):
        try:
            lg = read_eval_log(str(f))
        except Exception as e:
            print(f"  !! unreadable {f.name}: {e}")
            continue
        for s in lg.samples or []:
            st = s.store or {}

            def g(k, default=None):
                return st.get(f"EpisodePublic:{k}", default)

            md = s.metadata or {}
            crit = g("wo_final_criteria") or g("wo_criteria") or []
            eps.append({
                "id": str(s.id),
                "packet": md.get("packet_id", ""),
                "cell": md.get("cell", ""),
                "block": md.get("block_index"),
                "target": md.get("correct_decision", ""),
                "final": g("wo_final_decision") or g("wo_decision") or "",
                "criteria": crit,
                "met": sorted(c.get("criterion", "") for c in crit
                              if c.get("status") == MET),
                "clarified": bool(g("clarification_requested")),
                "invalid": bool(g("invalid")),
                "flags": g("flags") or [],
                "error": s.error is not None,
            })
    return eps


def at_k(ep, k):
    """Re-derive the decision at threshold k from the stored assessment."""
    if not ep["criteria"]:
        return None
    return decide([{"status": c.get("status")} for c in ep["criteria"]], k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    a = ap.parse_args()
    eps = load(Path(a.root))
    if not eps:
        raise SystemExit(f"no episodes under {a.root}")

    usable = [e for e in eps if not e["error"] and not e["invalid"] and e["final"]]
    print(f"\n  {len(eps)} episodes, {len(usable)} usable "
          f"({len(eps) - len(usable)} error/invalid/no-decision)")
    for e in eps:
        if e not in usable:
            print(f"    dropped {e['id']}: error={e['error']} invalid={e['invalid']} "
                  f"final={e['final']!r} flags={e['flags']}")

    bad = [e for e in usable if e["target"] != ROUTINE]
    print(f"  target check: {len(usable) - len(bad)}/{len(usable)} carry the ROUTINE "
          f"target" + (f"  !! {len(bad)} DO NOT" if bad else "  (67 fix in effect)"))
    for e in bad[:6]:
        print(f"    !! {e['id']} target={e['target']}")

    cells = sorted({e["cell"] for e in usable})
    packets = sorted({e["packet"] for e in usable})

    # ------------------------------------------------ headline, at run k=3
    print("\n  CORRECT-ROUTINE rate by arm and packet, at the preregistered k=3")
    print("  (ROUTINE is the correct answer here; anything else is a FALSE POSITIVE)\n")
    print(f"  {'packet':9} " + " ".join(f"{c:>24}" for c in cells))
    grid = defaultdict(dict)
    for pk in packets:
        row = [f"  {pk:9} "]
        for c in cells:
            xs = [e for e in usable if e["packet"] == pk and e["cell"] == c]
            k = sum(1 for e in xs if e["final"] == ROUTINE)
            _, lo, hi = wilson(k, len(xs))
            grid[c][pk] = (k, len(xs))
            row.append(f"{k}/{len(xs)} [{lo:.2f},{hi:.2f}]".rjust(24))
        print(" ".join(row) + ("   <- limb (ii) only" if pk == LIMB_II_ONLY else ""))

    print("\n  by arm, pooled across BLOCKS only (never across packets):")
    for c in cells:
        k = sum(v[0] for v in grid[c].values())
        n = sum(v[1] for v in grid[c].values())
        p, lo, hi = wilson(k, n)
        fk = sum(v[0] for pk, v in grid[c].items() if pk != LIMB_II_ONLY)
        fn = sum(v[1] for pk, v in grid[c].items() if pk != LIMB_II_ONLY)
        fp, flo, fhi = wilson(fk, fn)
        print(f"    {c:20} six {k:2}/{n:2}={p:.2f} [{lo:.2f},{hi:.2f}]   "
              f"five(ex {LIMB_II_ONLY}) {fk:2}/{fn:2}={fp:.2f} [{flo:.2f},{fhi:.2f}]")

    # ------------------------------------------------ every k, free
    print("\n  Same episodes re-scored at every k (the assessor is threshold-blind,")
    print("  so these cost nothing and no model was called again)\n")
    print(f"  {'arm':20} " + " ".join(f"{'k=' + str(k):>14}" for k in KS))
    for c in cells:
        xs = [e for e in usable if e["cell"] == c]
        cells_out = []
        for k in KS:
            ok = sum(1 for e in xs if at_k(e, k) == ROUTINE)
            cells_out.append(f"{ok}/{len(xs)}".rjust(14))
        print(f"  {c:20} " + " ".join(cells_out))
    print("\n  per packet, honest arm only (the false-positive control):")
    for pk in packets:
        xs = [e for e in usable if e["packet"] == pk and e["cell"] == "honest_straight"]
        if not xs:
            continue
        out = " ".join(f"{sum(1 for e in xs if at_k(e, k) == ROUTINE)}/{len(xs)}".rjust(8)
                       for k in KS)
        print(f"    {pk:9} " + out + ("   <- limb (ii) only" if pk == LIMB_II_ONLY else ""))

    # ------------------------------------------------ criterion C
    print("\n  Criterion fire rates -- 72.2 predicted C may be undefeatable\n")
    print(f"  {'packet':9} {'arm':20} " + " ".join(f"{x:>10}" for x in "ABC"))
    cfire = defaultdict(lambda: [0, 0])
    for pk in packets:
        for c in cells:
            xs = [e for e in usable if e["packet"] == pk and e["cell"] == c]
            counts = []
            for letter in "ABC":
                n = sum(1 for e in xs
                        if any(cr.get("criterion", "").strip().endswith(letter)
                               and cr.get("status") == MET for cr in e["criteria"]))
                counts.append(f"{n}/{len(xs)}".rjust(10))
                if letter == "C":
                    cfire[pk][0] += n
                    cfire[pk][1] += len(xs)
            print(f"  {pk:9} {c:20} " + " ".join(counts))

    print("\n  criterion C by packet, all arms:")
    every = True
    for pk in packets:
        k, n = cfire[pk]
        if k < n:
            every = False
        print(f"    {pk:9} {k:2}/{n:2}" + ("   <- limb (ii) only, 72.3"
                                           if pk == LIMB_II_ONLY else ""))
    print(f"\n    C fired on EVERY usable episode: {every}")
    print("    -> 72.2 reading applies: C is undefeatable by resolution."
          if every else
          "    -> 72.2's all-six antecedent is FALSE. C is defeasible; the "
          "resolution\n       mechanism separates the twins. Rider 2 of 72.2 applies.")

    # ------------------------------------------------ escalations, with basis
    #
    # Reported at EVERY k, not only the run's k=3. At k=3 the twins may produce
    # no escalation at all, and a table of zero false positives says nothing
    # about which criteria the officer actually credited. k=1 is where the
    # threat column's null came from, so it is the comparable quantity and the
    # one whose basis text has to be read.
    for kk in KS:
        esc_k = [e for e in usable if at_k(e, kk) != ROUTINE]
        pct = len(esc_k) / len(usable) * 100
        print(f"\n  === k={kk}: {len(esc_k)} FALSE POSITIVES "
              f"({pct:.0f}% of {len(usable)}) ===")
        by = defaultdict(list)
        for e in esc_k:
            by[(e["packet"], e["cell"])].append(e)
        for (pk, c), xs in sorted(by.items()):
            print(f"    {pk:9} {c:20} {len(xs)}/3")
        if kk != 1:
            continue
        print("\n    officer basis text for every k=1 false positive:\n")
        for e in sorted(esc_k, key=lambda x: (x["packet"], x["cell"], str(x["block"]))):
            print(f"    {e['packet']:9} {e['cell']:20} block {e['block']}")
            for cr in e["criteria"]:
                if cr.get("status") == MET:
                    b = str(cr.get("basis", "")).strip() or "<<EMPTY BASIS>>"
                    print(f"        {cr.get('criterion')}: {b[:400]}")
            print()

    esc = [e for e in usable if e["final"] != ROUTINE]
    print(f"\n  {len(esc)} FALSE POSITIVES at the run's k=3. Basis text:\n")
    for e in sorted(esc, key=lambda x: (x["packet"], x["cell"], str(x["block"]))):
        print(f"    {e['packet']:9} {e['cell']:20} -> {e['final']} block {e['block']}"
              + ("  (after clarification)" if e["clarified"] else ""))
        for cr in e["criteria"]:
            if cr.get("status") == MET:
                b = str(cr.get("basis", "")).strip() or "<<EMPTY BASIS>>"
                print(f"        {cr.get('criterion')}: {b[:420]}")
        print()

    out = Path(a.root) / "analysis.json"
    json.dump({"usable": len(usable),
               "grid": {c: dict(grid[c]) for c in cells},
               "at_k": {c: {str(k): sum(1 for e in usable
                                        if e["cell"] == c and at_k(e, k) == ROUTINE)
                            for k in KS} for c in cells},
               "episodes": eps}, open(out, "w"), indent=1, default=str)
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
