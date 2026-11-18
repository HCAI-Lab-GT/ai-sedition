"""Inter-rater reliability for the Run D fidelity-and-criterion adjudication.

Reports Cohen's kappa per label dimension, and -- the question that actually
matters -- whether the conclusions registered in PREREGISTRATION 105.9 hold when
recomputed on the second rater's labels instead of the first's. A high kappa on
a dimension nobody's conclusion rests on is not reassurance.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

DIMS = (
    "a_source_fidelity",
    "b_states_relationship",
    "c_cross_block_only",
    "d_officer_basis_valid",
)


def cohen_kappa(a: list[str], b: list[str]) -> tuple[float, float]:
    """Return (kappa, observed agreement). Undefined kappa returns nan."""
    n = len(a)
    if n == 0:
        return math.nan, math.nan
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1.0:
        return math.nan, po
    return (po - pe) / (1 - pe), po


def interpret(k: float) -> str:
    if math.isnan(k):
        return "undefined (no variance)"
    for lo, s in ((0.81, "almost perfect"), (0.61, "substantial"), (0.41, "moderate"),
                  (0.21, "fair"), (0.0, "slight")):
        if k >= lo:
            return s
    return "worse than chance"


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return math.nan
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2**n)


def load(path: Path) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    eps = raw if isinstance(raw, list) else [e for r in raw for e in r["episodes"]]
    return {e["episode_id"]: e for e in eps}


def headline(eps: list[dict], label: str) -> None:
    """Recompute the 105 tables on one rater's labels."""
    routine = lambda e: "ROUT" in str(e["outcome"]).upper()  # noqa: E731
    faithful = lambda e: e["a_source_fidelity"] == "faithful"  # noqa: E731
    valid = lambda e: e["d_officer_basis_valid"] == "valid"  # noqa: E731

    print(f"\n--- 105 tables recomputed on {label} ---")
    for name, pred in (
        ("registered ROUTINE", routine),
        ("source-faithful ROUTINE", lambda e: routine(e) and faithful(e)),
        ("faithful + valid basis", lambda e: routine(e) and faithful(e) and valid(e)),
    ):
        counts = {c: sum(1 for e in eps if e["condition"] == c and pred(e)) for c in ("basic", "strategic")}
        pairs: dict[tuple, dict[str, bool]] = {}
        for e in eps:
            pairs.setdefault((e["episode_id"].split("-b")[0], e["block"]), {})[e["condition"]] = pred(e)
        bo = sum(1 for s in pairs.values() if len(s) == 2 and s["basic"] and not s["strategic"])
        so = sum(1 for s in pairs.values() if len(s) == 2 and s["strategic"] and not s["basic"])
        p = mcnemar_exact(bo, so)
        print(f"  {name:24s} basic {counts['basic']:2d}  strategic {counts['strategic']:2d}"
              f"   discordant {bo}/{so}  McNemar p={p:.3f}")

    print(f"  relationship gradient ({label}):", end="")
    for lvl in ("explicit", "partial", "absent"):
        s = [e for e in eps if e["b_states_relationship"] == lvl]
        k = sum(1 for e in s if routine(e))
        print(f"  {lvl} {k}/{len(s)}", end="")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rater1", default="docs/audits/rund_adjudicated_audit.json")
    ap.add_argument("--rater2", default="docs/audits/rund_adjudicated_audit_rater2.json")
    ap.add_argument("--outcomes", default="docs/audits/rund_briefing_audit.json")
    a = ap.parse_args()

    r1, r2 = load(Path(a.rater1)), load(Path(a.rater2))
    # Rater 2 is blinded and never sees outcomes; graft them on for the tables.
    outcomes = {e["episode_id"]: e["outcome"] for e in json.loads(Path(a.outcomes).read_text(encoding="utf-8"))}
    shared = sorted(set(r1) & set(r2))
    print(f"rater1 {len(r1)} episodes | rater2 {len(r2)} | overlap {len(shared)}")
    if missing := (set(r1) ^ set(r2)):
        print(f"  NOT SHARED ({len(missing)}): {sorted(missing)[:6]}")
    if not shared:
        print("no overlap -- cannot compute reliability")
        return 1

    print("\n=== Cohen's kappa per dimension ===")
    kappas = {}
    for d in DIMS:
        k, po = cohen_kappa([r1[e][d] for e in shared], [r2[e][d] for e in shared])
        kappas[d] = k
        print(f"  {d:24s} kappa={k:6.3f}  agreement={po:5.1%}  ({interpret(k)})")

    print("\n=== per-class agreement and prevalence ===")
    print("  kappa is prevalence-sensitive: a dimension dominated by one class can")
    print("  show low kappa despite high raw agreement. Read these together.")
    for d in DIMS:
        a = [r1[e][d] for e in shared]
        b = [r2[e][d] for e in shared]
        print(f"  {d}  raw agreement {sum(x == y for x, y in zip(a, b)) / len(a):.1%}")
        for c in sorted(set(a) | set(b)):
            n1, n2 = a.count(c), b.count(c)
            both = sum(1 for x, y in zip(a, b) if x == c and y == c)
            psa = 2 * both / (n1 + n2) if (n1 + n2) else float("nan")
            print(f"     {c:26s} r1={n1:3d} r2={n2:3d} both={both:3d}"
                  f"  specific-agreement={psa:6.1%}"
                  f"  prevalence={max(n1, n2) / len(a):6.1%}")
    print()
    print("\n=== disagreements by dimension ===")
    for d in DIMS:
        diff = [(e, r1[e][d], r2[e][d]) for e in shared if r1[e][d] != r2[e][d]]
        if not diff:
            continue
        print(f"  {d} ({len(diff)}):")
        for e, x, y in diff[:12]:
            print(f"     {e:34s} r1={x:24s} r2={y}")
        if len(diff) > 12:
            print(f"     ... {len(diff)-12} more")

    for lbl, r in (("rater 1", r1), ("rater 2", r2)):
        eps = []
        for e in shared:
            rec = dict(r[e])
            rec["outcome"] = outcomes.get(e, r1[e].get("outcome"))
            eps.append(rec)
        headline(eps, lbl)

    out = {
        "n": len(shared),
        "raw_agreement": {d: round(sum(r1[e][d] == r2[e][d] for e in shared) / len(shared), 4)
                          for d in DIMS},
        "per_class": {d: {c: {"rater1": [r1[e][d] for e in shared].count(c),
                              "rater2": [r2[e][d] for e in shared].count(c),
                              "both": sum(1 for e in shared if r1[e][d] == c == r2[e][d])}
                          for c in sorted({r1[e][d] for e in shared} | {r2[e][d] for e in shared})}
                      for d in DIMS},
        "kappa": {d: (None if math.isnan(k) else round(k, 4)) for d, k in kappas.items()},
        "disagreements": {
            d: [{"episode_id": e, "rater1": r1[e][d], "rater2": r2[e][d]}
                for e in shared if r1[e][d] != r2[e][d]]
            for d in DIMS
        },
    }
    Path("docs/audits/rund_irr.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\nwrote docs/audits/rund_irr.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
