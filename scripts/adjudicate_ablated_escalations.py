"""Hand-adjudicate the k=1 false positives from the 74 column.

The question per episode: does the TWIN TEXT still satisfy the criterion the
officer cited? If yes, the escalation is CORRECT and the episode is
under-ablation, not officer error. Counting it as a false positive understates
the officer and overstates the control.

This does not decide by keyword. For each escalation it pulls the officer's own
basis, then pulls the twin sentences the basis points at, so the two can be read
side by side. The verdict column is a proposal; the reading is the point.

75.5 predicts E01-MS and E03-MS are under-ablated and the SS twins are not.
"""
from __future__ import annotations

import glob
import os
import re
import sys
from collections import defaultdict

os.chdir(__import__("pathlib").Path(__file__).resolve().parents[1])  # repo root; inputs live in gitignored logs/
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inspect_ai.log import read_eval_log

from sedition.enums import Decision
from sedition.packets import variants

variants.ALLOW_DRAFT_TWINS = True
from sedition.packets.variants import resolve_packet  # noqa: E402
from sedition.scoring.threshold_rule import decide  # noqa: E402

ROUTINE = Decision.INCLUDE_IN_ROUTINE_UPDATE.value

#: The comparable column of 74: honest + basic + strategic@shade_v17.
SRC = [("logs/ablated54/honest_straight__ablated/**/*.eval", "honest"),
       ("logs/ablated54/basic_straight__ablated/**/*.eval", "basic"),
       ("logs/ablated-strat-v17/**/*.eval", "strategic")]


def load():
    out = []
    for pat, arm in SRC:
        for f in sorted(glob.glob(pat, recursive=True)):
            try:
                lg = read_eval_log(f)
            except Exception:
                continue
            for s in lg.samples or []:
                st = s.store or {}
                crit = (st.get("EpisodePublic:wo_final_criteria")
                        or st.get("EpisodePublic:wo_criteria") or [])
                md = s.metadata or {}
                out.append({"arm": arm, "packet": md.get("packet_id"),
                            "block": md.get("block_index"), "criteria": crit})
    return out


def at_k(e, k):
    return decide([{"status": c.get("status")} for c in e["criteria"]], k) \
        if e["criteria"] else None


def sentences(pid):
    tw = resolve_packet(pid, "ablated")
    out = []
    for r in tw.reports:
        for s in re.split(r"(?<=[.!?])\s+", r.text):
            s = s.strip()
            if len(s) > 30:
                out.append((r.report_id, s))
    return out


def evidence_for(pid, basis, limit=3):
    """Twin sentences sharing distinctive tokens with the officer's basis."""
    toks = {t for t in re.findall(r"\b[A-Z]{2,}-[\w\d]+|\b[A-Z]{2,}\b|\b\d{4}K\b", basis)
            if len(t) > 2}
    if not toks:
        return []
    scored = []
    for rid, s in sentences(pid):
        hit = toks & set(re.findall(r"\b[A-Z]{2,}-[\w\d]+|\b[A-Z]{2,}\b|\b\d{4}K\b", s))
        if hit:
            scored.append((len(hit), rid, s, sorted(hit)))
    scored.sort(reverse=True)
    return scored[:limit]


eps = load()
fp = [e for e in eps if e["criteria"] and at_k(e, 1) != ROUTINE]
print(f"  {len(eps)} episodes in the comparable column, "
      f"{len(fp)} k=1 false positives to adjudicate\n")

by_pkt = defaultdict(list)
for e in fp:
    by_pkt[e["packet"]].append(e)

verdicts = defaultdict(list)
for pid in sorted(by_pkt):
    print("=" * 76)
    print(f"  {pid}   ({len(by_pkt[pid])} escalations)")
    print("=" * 76)
    for e in sorted(by_pkt[pid], key=lambda x: (x["arm"], str(x["block"]))):
        met = [c for c in e["criteria"] if c.get("status") == "met"]
        print(f"\n  [{e['arm']}, block {e['block']}]  criteria met: "
              f"{', '.join(c.get('criterion', '?') for c in met)}")
        for c in met:
            b = str(c.get("basis", "")).strip()
            print(f"\n    {c.get('criterion')} -- officer's basis:")
            print(f"      {b[:300]}")
            ev = evidence_for(pid, b)
            if not ev:
                print("      twin evidence: none located (basis cites nothing traceable)")
                verdicts[pid].append("unlocatable")
                continue
            print("      twin sentences the basis points at:")
            for _, rid, s, hit in ev:
                print(f"        [{rid}] {s[:170]}")
                print(f"              shared: {', '.join(hit[:6])}")
            verdicts[pid].append("supported")
    print()

print("=" * 76)
print("  PROPOSED SPLIT")
print("=" * 76)
for pid in sorted(by_pkt):
    v = verdicts[pid]
    sup = v.count("supported")
    print(f"  {pid:9} {len(by_pkt[pid])} escalations | "
          f"{sup} with locatable twin evidence, {v.count('unlocatable')} without")
print("\n  75.5 predicted UNDER-ABLATED: E01-MS, E03-MS")
print(f"  packets that actually leaked: {', '.join(sorted(by_pkt))}")
