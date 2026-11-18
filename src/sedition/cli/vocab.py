"""`sedition vocab ...` — validate the fact vocabulary and generate the sheet
a human reviews it from."""
from __future__ import annotations

from pathlib import Path

from ..packets.answer_key import load_answer_key
from ..packets.build import parse_all, parse_all_including_heldout
from ..packets.fact_vocabulary import load_fact_vocabulary, validate_vocabulary
from ..packets.review_sheet import build_review_sheet, write_review_sheet
from ..storage.paths import ANSWER_KEY_JSON, PACKAGE_ROOT, REPO_ROOT, SCENARIOS_DIR

VOCAB_PATH = PACKAGE_ROOT / "packets" / "fact_vocabulary.yaml"


def _decisive_reports() -> dict[str, tuple[str, ...]]:
    """The minimal criterion-satisfying set per packet, from the answer key.
    Used to locate each single-source packet's decisive report."""
    if not ANSWER_KEY_JSON.exists():
        return {}
    key = load_answer_key(ANSWER_KEY_JSON)
    out: dict[str, tuple[str, ...]] = {}
    for pid, pk in key.packets.items():
        sets = pk.minimal_criterion_satisfying_report_sets
        if sets:
            out[pid] = tuple(sorted(sets, key=len)[0])
    return out


def validate_main(*, require_reviewed: bool = False) -> int:
    vocab = load_fact_vocabulary(VOCAB_PATH)
    packages = parse_all_including_heldout(SCENARIOS_DIR)
    packet_ids = {pid: p.report_ids
                  for pkg in packages.values() for pid, p in pkg.packets.items()}
    # The computed-anchor precondition needs report TEXT, not just ids.
    packet_texts = {pid: "\n".join(r.text for r in p.reports)
                    for pkg in packages.values() for pid, p in pkg.packets.items()}
    errors, warnings = validate_vocabulary(vocab, packet_ids,
                                           require_reviewed=require_reviewed,
                                           packet_texts=packet_texts)

    print(f"fact vocabulary: {vocab.total_facts()} facts, version {vocab.version}")
    print(f"cleared: {vocab.total_facts() - len(vocab.draft_facts)} / {vocab.total_facts()}")
    print()
    for pid in vocab.packet_ids():
        facts = vocab.for_packet(pid)
        print(f"  {pid}: {len(facts):2d} facts  "
              f"atomic={sum(1 for f in facts if f.is_atomic)} "
              f"derived={sum(1 for f in facts if f.is_derived)} "
              f"decoy={sum(1 for f in facts if f.is_decoy)}")
    print()
    if errors:
        print(f"ERRORS ({len(errors)}) — these block preflight:")
        for e in errors:
            print(f"  {e.fact_id}  {e.code}: {e.message}")
    if warnings:
        print(f"WARNINGS ({len(warnings)}) — require reviewer sign-off:")
        for w in warnings:
            print(f"  {w.fact_id}  {w.code}: {w.message}")
    if not errors and not warnings:
        print("0 errors, 0 warnings.")
    if not vocab.is_reviewed:
        print()
        print("NOT CLEARED FOR SCORING. Run `sedition vocab review-sheet`, work "
              "through it, then set review.status per fact.")
    return 1 if errors else 0


def review_sheet_main(*, packet: str | None = None, out: str | Path | None = None) -> int:
    vocab = load_fact_vocabulary(VOCAB_PATH)
    packages = parse_all_including_heldout(SCENARIOS_DIR)
    text = build_review_sheet(vocab, packages, _decisive_reports(), packet_filter=packet)
    out_dir = Path(out) if out else REPO_ROOT / "docs" / "review"
    path = write_review_sheet(text, out_dir)
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"{vocab.total_facts()} facts, "
          f"{len(vocab.draft_facts)} awaiting review")
    return 0
