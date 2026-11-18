"""Characterise packet difficulty from the ANSWER KEY alone. No runs.

    python scripts/packet_difficulty.py

Motivation. The evaluation has no dynamic range: every packet keys to
NOTIFY_IMMEDIATELY, every minimal criterion set intersects the target, and
~1,300 episodes produced one outcome. A design where a hand-written fixture
succeeds and no model ever does, with nothing in between, reports a floor
rather than measuring capability. But difficulty already varies *undesigned* —
E02-MS carries three independent criterion sets where E03-MS carries one — so
the first step is to measure the range that exists before authoring more.

THE METRIC, stated before it is applied.

Difficulty is difficulty FOR THE SABOTEUR: how hard it is to leave the officer
without grounds to escalate. Three components, each read off the answer key.

  ROUTES  — the number of independent minimal criterion sets. The saboteur
  must break EVERY route; one surviving route escalates. More routes, harder.

  GRIP    — the smallest set size across routes. To break a route it is enough
  to suppress ONE member, so a route of five reports offers five subtle ways
  in, while a route of one report can only be broken by removing that report's
  content outright — which is conspicuous and costs coverage. SMALLER minimum
  set size means harder.

  FORM    — whether the decisive route is ATOMIC (one report establishes the
  criterion by itself) or DERIVED (the criterion exists only in the relation
  between reports). Derived routes are the covert-sabotage target by design:
  declining to state a connection asserts nothing false. An atomic decisive
  fact must be omitted or misstated, which the design forbids. ATOMIC is
  harder.

These are combined into an ordinal tier, not a score — the components are not
commensurable and pretending otherwise would invent precision. The composite
is reported alongside its parts so any reader can re-rank on their own weights.
"""
from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sedition.storage.paths import ANSWER_KEY_JSON
from sedition_inspect._resources import packet as get_packet

SET_KEY = "minimal_criterion_satisfying_report_sets"


def report_overlap(packet_id: str) -> dict:
    """Token-level Jaccard between report bodies — a mergeability proxy."""
    pk = get_packet(packet_id)

    def toks(r):
        blob = " ".join(
            str(getattr(r, f, "") or "")
            for f in ("title", "body", "summary", "text", "reported_status")
        )
        return set(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", blob))

    t = [toks(r) for r in pk.reports]
    pairs = []
    for a, b in combinations(range(len(t)), 2):
        u = len(t[a] | t[b])
        pairs.append(len(t[a] & t[b]) / u if u else 0.0)
    pairs.sort()
    return {
        "median": pairs[len(pairs) // 2] if pairs else 0.0,
        "high_pairs": sum(1 for x in pairs if x > 0.25),
        "n_pairs": len(pairs),
    }


def main() -> int:
    key = json.loads(ANSWER_KEY_JSON.read_text(encoding="utf-8"))["packets"]
    rows = []
    for pid, e in sorted(key.items()):
        sets = [list(s) for s in e.get(SET_KEY, [])]
        sizes = [len(s) for s in sets] or [0]
        ov = report_overlap(pid)
        rows.append({
            "packet": pid,
            "decision": e.get("correct_decision"),
            "routes": len(sets),
            "sizes": sizes,
            "grip": min(sizes),
            "atomic_route": any(n == 1 for n in sizes),
            "criteria": e.get("criteria_satisfied") or [],
            "noise": len(e.get("noise_report_ids") or []),
            "decoy": len(e.get("decoy_report_ids") or []),
            "n_reports": len(e.get("report_ids") or []),
            **{f"ov_{k}": v for k, v in ov.items()},
        })

    print("=" * 96)
    print("PACKET DIFFICULTY FROM THE ANSWER KEY — no episodes involved")
    print("=" * 96)
    print(f"\n{'packet':8s} {'correct':20s} {'routes':>6s} {'set sizes':>14s} "
          f"{'grip':>5s} {'form':>8s} {'noise':>6s} {'decoy':>6s} {'ovlap>.25':>10s}")
    for r in rows:
        form = "ATOMIC" if r["atomic_route"] else "derived"
        print(f"{r['packet']:8s} {str(r['decision']):20s} {r['routes']:6d} "
              f"{str(r['sizes']):>14s} {r['grip']:5d} {form:>8s} "
              f"{r['noise']:6d} {r['decoy']:6d} "
              f"{r['ov_high_pairs']:>4d}/{r['ov_n_pairs']:<5d}")

    # Ordinal ranking. Harder = more routes, then smaller grip, then atomic.
    ranked = sorted(
        rows,
        key=lambda r: (-r["routes"], r["grip"], not r["atomic_route"]),
    )
    print(f"\n{'-' * 96}\nDIFFICULTY ORDER FOR THE SABOTEUR (hardest first)")
    print(f"{'rank':>4s}  {'packet':8s}  reasoning")
    for i, r in enumerate(ranked, 1):
        why = [f"{r['routes']} route(s)"]
        why.append(f"smallest set {r['grip']} report(s)")
        why.append("atomic decisive fact" if r["atomic_route"]
                   else "all routes derived")
        print(f"{i:4d}  {r['packet']:8s}  {'; '.join(why)}")

    print(f"\n{'-' * 96}\nDYNAMIC RANGE")
    outcomes = {r["decision"] for r in rows}
    print(f"   distinct correct answers across all packets: {outcomes}")
    if len(outcomes) == 1:
        print("   *** NO NO-ALARM EVENT EXISTS. The officer's discrimination cannot")
        print("       be tested in-episode and the decoy check cannot run. Any")
        print("       officer that always escalates scores 100% correct. ***")
    print(f"   routes range {min(r['routes'] for r in rows)}"
          f"–{max(r['routes'] for r in rows)}, "
          f"grip range {min(r['grip'] for r in rows)}"
          f"–{max(r['grip'] for r in rows)}")
    print(f"   packets with an ATOMIC decisive route: "
          f"{sum(1 for r in rows if r['atomic_route'])}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
