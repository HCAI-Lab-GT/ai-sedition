"""Say exactly WHY a briefing earned WRONG_BLOCK_FORM.

    python scripts/diagnose_block_form.py logs/rung7 [more dirs...]

`validate_briefing_format` returns a flag set and no reasons, so a rung that
starts flagging cannot be told apart into "the model dropped a label" and "the
merge instruction is fighting the required form". Rung 7 makes that distinction
load-bearing: it asks the analyst to combine reports into fewer incidents, and
if fewer-but-malformed blocks are the result then its block-count win is bought
with compliance and is not comparable to `hollow-compliant`, which is fully
compliant at 5 blocks.

This re-runs the same three rules the validator applies, per block, and reports
which one fired. It imports the real constants rather than restating them, so
it cannot drift from the validator it explains.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inspect_ai.log import list_eval_logs, read_eval_log

from sedition.agents.analyst import (
    COMPACT_FORM_FIELDS,
    FULL_FORM_FIELDS,
    parse_briefing,
)
from sedition.pipeline.validate import OPEN_STATUSES, TITLE_FIELD, _field_body
from sedition_inspect._resources import packet as get_packet

#: The three routes to WRONG_BLOCK_FORM, in the order the validator checks
#: them. Only the last is unambiguously a merge/form conflict; the first two
#: can also be a model that simply wrote the wrong shape.
RULE_FULL_SHAPE = "needs full form, is not full form (and >1 field absent)"
RULE_COMPACT_SHAPE = "compact block missing a compact field"
RULE_EMPTY_FIELD = "full-form block has a REQUIRED FIELD PRESENT BUT EMPTY"


def diagnose(text: str, packet_id: str) -> list[dict]:
    pk = get_packet(packet_id)
    status_by_id = {r.report_id: (r.reported_status or "").lower() for r in pk.reports}
    out = []
    for i, block in enumerate(parse_briefing(text).blocks, start=1):
        needs_full = any(
            any(s in status_by_id.get(rid, "") for s in OPEN_STATUSES)
            for rid in block.cited_report_ids
        )
        expected = FULL_FORM_FIELDS if needs_full else COMPACT_FORM_FIELDS
        absent = [f for f in expected if f not in block.text]
        cosmetic_only = absent == [TITLE_FIELD]

        rules, empties = [], []
        if needs_full and not block.is_full_form and not cosmetic_only:
            rules.append(RULE_FULL_SHAPE)
        if (not needs_full and not cosmetic_only
                and not (block.is_full_form
                         or all(f in block.text for f in COMPACT_FORM_FIELDS))):
            rules.append(RULE_COMPACT_SHAPE)
        if block.is_full_form:
            empties = [f for f in FULL_FORM_FIELDS
                       if _field_body(block.text, f, FULL_FORM_FIELDS) == ""]
            if empties:
                rules.append(RULE_EMPTY_FIELD)
        if rules:
            out.append({
                "block": i, "rules": rules, "absent": absent, "empty": empties,
                "needs_full": needs_full, "n_reports": len(block.cited_report_ids),
                "cited": block.cited_report_ids,
            })
    return out


def main() -> int:
    roots = sys.argv[1:] or ["logs/rung7"]
    rule_hits, merged_sizes, clean_sizes = Counter(), [], []
    field_absent, field_empty = Counter(), Counter()
    episodes = flagged = 0

    for root in roots:
        for d in sorted(Path(root).glob("b*")):
            for info in list_eval_logs(str(d)):
                for s in read_eval_log(info.name).samples or []:
                    st = s.store
                    text = st.get("EpisodePublic:public_briefing") or ""
                    if not text.strip():
                        continue
                    episodes += 1
                    bad = diagnose(text, s.metadata.get("packet_id"))
                    if "WRONG_BLOCK_FORM" not in (st.get("EpisodePublic:flags") or []):
                        for blk in parse_briefing(text).blocks:
                            clean_sizes.append(len(blk.cited_report_ids))
                        continue
                    flagged += 1
                    for b in bad:
                        for r in b["rules"]:
                            rule_hits[r] += 1
                        for f in b["absent"]:
                            field_absent[f] += 1
                        for f in b["empty"]:
                            field_empty[f] += 1
                        merged_sizes.append(b["n_reports"])

    print(f"{'=' * 74}\nWRONG_BLOCK_FORM diagnosis — {', '.join(roots)}\n{'=' * 74}")
    print(f"\nepisodes with a briefing : {episodes}")
    print(f"flagged WRONG_BLOCK_FORM : {flagged}"
          f"{f'  ({flagged/episodes:.0%})' if episodes else ''}")
    if not flagged:
        print("\nnothing flagged — no diagnosis to make.")
        return 0

    print("\nWHICH RULE FIRED (per offending block)")
    for rule, n in rule_hits.most_common():
        print(f"   {n:4d}  {rule}")

    print("\nFIELDS ABSENT ENTIRELY (label not written at all)")
    for f, n in field_absent.most_common():
        print(f"   {n:4d}  {f}")
    print("\nFIELDS PRESENT BUT EMPTY (label written, no body under it)")
    for f, n in field_empty.most_common() or [("(none)", 0)]:
        print(f"   {n:4d}  {f}")

    if merged_sizes:
        m = sorted(merged_sizes)
        print(f"\nREPORTS PER OFFENDING BLOCK  median={m[len(m)//2]} "
              f"min={m[0]} max={m[-1]}")
    if clean_sizes:
        c = sorted(clean_sizes)
        print(f"REPORTS PER CLEAN BLOCK      median={c[len(c)//2]} "
              f"min={c[0]} max={c[-1]}")

    # The question rung 7 actually needs answered.
    #
    # Which RULE fired is not sufficient to answer it. The decisive evidence is
    # whether the offending blocks are the MERGED ones: if failures concentrate
    # in blocks citing many reports while single-report blocks stay clean, the
    # merge instruction is what produced the failure, whichever rule caught it.
    print("\nVERDICT")
    if not merged_sizes:
        print("   no offending blocks to characterise.")
        return 0
    med_bad = sorted(merged_sizes)[len(merged_sizes) // 2]
    med_ok = sorted(clean_sizes)[len(clean_sizes) // 2] if clean_sizes else 0
    concentrated = med_bad >= 2 * max(med_ok, 1)

    if concentrated:
        print(f"   GENUINE MERGE/FORM CONFLICT. Offending blocks cite a median of")
        print(f"   {med_bad} reports against {med_ok} in clean blocks — the failures are")
        print( "   concentrated in exactly the blocks that did what rung 7 asked.")
        if rule_hits[RULE_EMPTY_FIELD] and not rule_hits[RULE_FULL_SHAPE]:
            print("   Mechanism: labels written, a required field left empty.")
        else:
            print("   Mechanism: on merging, the block DROPS required field labels")
            print("   outright and falls back to a shorter form than the reports'")
            print("   status requires. Not the cosmetic missing-title case — the")
            print("   validator routes that to MISSING_FIELD_LABEL.")
        print( "   CONSEQUENCE: rung 7's block-count reduction is partly bought with")
        print( "   compliance, so it is NOT directly comparable to hollow-compliant,")
        print( "   which reaches 5 blocks fully compliant. Report the flag rate beside")
        print( "   the block count, and treat flagged episodes as a separate stratum.")
    else:
        print(f"   NOT CONCENTRATED IN MERGED BLOCKS. Offending blocks cite a median")
        print(f"   of {med_bad} reports against {med_ok} in clean blocks, so this looks like")
        print( "   ordinary form failure rather than a cost of merging.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
