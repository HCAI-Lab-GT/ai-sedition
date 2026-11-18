"""The anti-vacuity check the whole ablated column rests on.

At k=3 every ablated episode is ROUTINE and ROUTINE is correct, so the scorer
reads 100%. That number is worthless on its own: an officer that says ROUTINE to
everything would produce exactly the same table. The control has to show the
SAME officer escalating on the threat stimulus.

Honest arm only, both columns, same officer seat and standard. Reported at every
k because the assessor is threshold-blind, and because the threat column ran
k=1 while the ablated column ran k=3 -- only a k-matched comparison is
meaningful.
"""
from __future__ import annotations

import glob
import math
import os
import sys

os.chdir(__import__("pathlib").Path(__file__).resolve().parents[1])  # repo root; inputs live in gitignored logs/
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inspect_ai.log import read_eval_log

from sedition.enums import Decision
from sedition.scoring.threshold_rule import decide

ROUTINE = Decision.INCLUDE_IN_ROUTINE_UPDATE.value
TWINS = {"E01-SS", "E01-MS", "E02-SS", "E02-MS", "E03-SS", "E03-MS"}


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def load(pattern, cell="honest_straight"):
    out = []
    for f in sorted(glob.glob(pattern, recursive=True)):
        try:
            lg = read_eval_log(f)
        except Exception:
            continue
        for s in lg.samples or []:
            md = s.metadata or {}
            if md.get("cell") != cell or md.get("packet_id") not in TWINS:
                continue
            st = s.store or {}
            crit = (st.get("EpisodePublic:wo_final_criteria")
                    or st.get("EpisodePublic:wo_criteria") or [])
            if not crit:
                continue
            out.append({"packet": md["packet_id"], "criteria": crit})
    return out


def at_k(e, k):
    return decide([{"status": c.get("status")} for c in e["criteria"]], k)


threat = load("logs/threat240/**/*.eval")
abl = load("logs/ablated54/**/*.eval")
print(f"\n  honest arm, six twin packets: {len(threat)} threat, {len(abl)} ablated\n")
if not threat:
    print("  !! no threat episodes loaded -- comparison cannot be made")
    sys.exit(1)

print(f"  {'k':>3}  {'threat NOTIFY':>16}  {'ablated NOTIFY':>16}   separation")
for k in (1, 2, 3):
    tn = sum(1 for e in threat if at_k(e, k) != ROUTINE)
    an = sum(1 for e in abl if at_k(e, k) != ROUTINE)
    tp, tlo, thi = wilson(tn, len(threat))
    ap, alo, ahi = wilson(an, len(abl))
    sep = "YES" if tlo > ahi else ("no" if tp <= ap else "overlapping")
    print(f"  {k:>3}  {tn:3}/{len(threat):<3} {tp:.2f} [{tlo:.2f},{thi:.2f}]"
          f"  {an:3}/{len(abl):<3} {ap:.2f} [{alo:.2f},{ahi:.2f}]   {sep}")

print("\n  per packet, k=1 (the threat column's own threshold):")
print(f"  {'packet':9} {'threat':>14} {'ablated':>14}")
for pk in sorted(TWINS):
    t = [e for e in threat if e["packet"] == pk]
    a = [e for e in abl if e["packet"] == pk]
    tn = sum(1 for e in t if at_k(e, 1) != ROUTINE)
    an = sum(1 for e in a if at_k(e, 1) != ROUTINE)
    print(f"  {pk:9} {tn:5}/{len(t):<8} {an:5}/{len(a):<8}")

print("\n  READING: the ablated column's k=3 100% is only meaningful if the same")
print("  officer escalates on the threat stimulus. Where the threat rate is high")
print("  and the ablated rate is low at the same k, the twins are doing their job.")
