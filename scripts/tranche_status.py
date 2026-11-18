"""KEPT DELIBERATELY — progress reporting for the deep-pilot tranches.

Not used by new work. Retained alongside `run_phase2.py` for the same reason:
it is part of how the 749-episode baseline was produced and monitored.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sedition.pipeline import failure_policy as fp
from sedition.scoring import stopping

from sedition_inspect.episodes import episode_rows, provider_calls


def main() -> int:
    dirs = sys.argv[1:]
    if not dirs:
        print(__doc__)
        return 2

    rows = []
    errors = calls = 0
    for d in dirs:
        rows.extend(episode_rows(d))
        e, c = provider_calls(d)
        errors += e
        calls += c
    if not rows:
        print(f"no episodes found in {dirs}")
        return 1

    cells = sorted({r["cell"] for r in rows if r.get("cell")})
    print(f"TRANCHE STATUS — {len(rows)} episodes across {len(dirs)} dir(s)\n")

    hdr = (f"{'cell':22s} {'n':>3s} {'invalid':>8s} {'degen':>6s} {'trunc':>6s} "
           f"{'selmal':>7s} {'womal':>6s} {'drs-cov':>8s} {'cnt-facts':>10s}")
    print(hdr)
    for cell in cells:
        sub = [r for r in rows if r.get("cell") == cell]
        d = fp.denominators(sub)
        flags = Counter(f for r in sub for f in (r.get("flags") or []))
        drs_cov = d["drs"] / d["counted"] if d["counted"] else 0
        print(f"{cell:22s} {len(sub):3d} "
              f"{sum(1 for r in sub if r['invalid']):8d} "
              f"{flags.get('DEGENERATE_OUTPUT', 0):6d} "
              f"{flags.get('TRUNCATED', 0):6d} "
              f"{flags.get('SELECTION_MALFORMED', 0):7d} "
              f"{flags.get('WO_MALFORMED', 0):6d} "
              f"{drs_cov:8.0%} "
              f"{d['counted'] - d['facts']:10d}")

    d = fp.denominators(rows)
    print(f"\ndenominators (all cells): "
          + "  ".join(f"{k}={v}" for k, v in d.items() if not isinstance(v, dict)))
    x = d["excluded_from_facts"]
    print(f"excluded from facts: total={x['total']} "
          f"(fatal={x['fatal']} degenerate={x['degenerate']} refused={x['refused']}) "
          f"— truncated episodes stay in; sensitivity n={d['facts_excl_truncated']}")

    verdict = stopping.evaluate(rows, scope="tranche so far", blocks=1,
                                provider_errors=errors, provider_calls=calls)
    print(f"\nstopping rules: {verdict.report()}")
    return 1 if verdict.stop else 0


if __name__ == "__main__":
    raise SystemExit(main())
