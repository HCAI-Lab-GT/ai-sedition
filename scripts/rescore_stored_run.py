"""Part B — re-score pilot01's 48 stored briefings under anchor-relation-v2.

The question this settles has been open since the pilot. Under the old
`lexical-overlap-v1` matcher, SHEET briefings scored 11.1pp lower than
STRAIGHT on derived facts. That matcher was LENGTH-SENSITIVE — it measured
what share of a fact's description words appeared in the briefing — and
pilot01's SHEET briefings ran 19% shorter. A shorter briefing has fewer
words, so fewer overlaps, so a lower score, whether or not it stated the
fact. The gap and the artifact are the same size, so the pilot could not
tell them apart.

`anchor-relation-v2` keys on tokens a briefing must actually contain, which
is length-insensitive by construction. Re-scoring the SAME text with it
separates the two.

No model calls. Reads stored text only.

CARRY THIS CAVEAT: pilot01 ran on analyst_common v5, before the §2.5 fix
that stopped the honest analyst adopting a source report's hedge instead of
performing the subtraction. Honest derived rates here describe a prompt that
no longer exists. What is comparable is SHEET vs STRAIGHT *within* pilot01,
because both arms shared that defect.
"""
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# `python scripts/rescore_stored_run.py` puts scripts/ on sys.path, not the repo
# root, so `sedition` was unimportable and the README's command failed at the
# import line before it ever reached the missing-run error. Fixed 2026-08-23.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sedition.packets.fact_vocabulary import load_fact_vocabulary
from sedition.scoring.facts import score_facts
from sedition.storage.paths import PACKAGE_ROOT

#: The stored run to re-score. Required -- this script has no default run, and
#: hardcoding one made the README command unrunnable for anyone else
#: (docs/AUDIT-2026-08-16.md:416; fixed in the 2026-08-23 release audit).
_run = os.environ.get("SEDITION_RUN") or (sys.argv[1] if len(sys.argv) > 1 else None)
if not _run:
    raise SystemExit(
        "usage: rescore_stored_run.py <run-episodes-dir>   (or set SEDITION_RUN)\n"
        "  the directory holding one subdirectory per episode")
RUN = Path(_run)

vocab = load_fact_vocabulary(PACKAGE_ROOT / "packets" / "fact_vocabulary.yaml")

rows = []
for ep in sorted(RUN.iterdir()):
    briefing_path = ep / "artifacts" / "briefing.txt"
    scores_path = ep / "scores.json"
    if not briefing_path.exists() or not scores_path.exists():
        print(f"  skipped {ep.name}: missing artifact")
        continue
    briefing = briefing_path.read_text(encoding="utf-8")
    stored = json.loads(scores_path.read_text(encoding="utf-8"))
    packet_id = stored["packet_id"]

    new = score_facts(vocab.for_packet(packet_id), briefing, vocabulary=vocab)
    old = stored["facts"]

    rows.append({
        "episode": ep.name,
        "packet": packet_id,
        "cell": stored["cell"],
        "policy": stored["policy"],
        "wc": stored["working_condition"],
        "words": len(briefing.split()),
        "old_atomic": old.get("atomic_rate"),
        "old_derived": old.get("derived_rate"),
        "new_atomic": round(new.atomic_rate, 4),
        "new_derived": round(new.derived_rate, 4),
    })

print(f"re-scored {len(rows)} episodes, 0 model calls\n")


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def table(group_key, title):
    print("=" * 86)
    print(title)
    print("=" * 86)
    print(f"{'group':22s} {'n':>3s} {'words':>6s} "
          f"{'atomic old':>11s} {'atomic new':>11s} "
          f"{'DERIVED old':>12s} {'DERIVED new':>12s}")
    groups = defaultdict(list)
    for r in rows:
        groups[group_key(r)].append(r)
    for g in sorted(groups):
        rs = groups[g]
        print(f"{g:22s} {len(rs):3d} {mean(r['words'] for r in rs):6.0f} "
              f"{mean(r['old_atomic'] for r in rs):11.3f} "
              f"{mean(r['new_atomic'] for r in rs):11.3f} "
              f"{mean(r['old_derived'] for r in rs):12.3f} "
              f"{mean(r['new_derived'] for r in rs):12.3f}")
    print()
    return groups


table(lambda r: r["cell"], "BY CELL")
by_wc = table(lambda r: r["wc"], "BY WORKING CONDITION  (the pilot's open question)")
table(lambda r: r["policy"], "BY POLICY")

# --- the headline ---------------------------------------------------------
sheet = [r for r in rows if r["wc"] == "SHEET"]
straight = [r for r in rows if r["wc"] == "STRAIGHT"]
for label, key in (("derived", "derived"), ("atomic", "atomic")):
    old_gap = mean(r[f"old_{key}"] for r in straight) - mean(r[f"old_{key}"] for r in sheet)
    new_gap = mean(r[f"new_{key}"] for r in straight) - mean(r[f"new_{key}"] for r in sheet)
    print(f"{label:8s} STRAIGHT - SHEET   old {old_gap*100:+6.1f}pp   new {new_gap*100:+6.1f}pp")

w_sheet, w_straight = mean(r["words"] for r in sheet), mean(r["words"] for r in straight)
print(f"\nbriefing length: SHEET {w_sheet:.0f} words, STRAIGHT {w_straight:.0f} "
      f"({(w_sheet/w_straight - 1)*100:+.1f}%)")

out = Path("part_b_rescore.json")
out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(f"\nper-episode detail: {out.resolve()}")
