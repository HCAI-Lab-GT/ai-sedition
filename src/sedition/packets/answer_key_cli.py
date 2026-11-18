"""`sedition build-key` and `sedition validate-key`.

The key is derived from the read-only scenario files plus the released trigger
rules. If the key and the files disagree, the files win and
validation reports the mismatch — the scenario prose is never edited to make
validation pass.
"""
from __future__ import annotations

from ..storage.paths import (
    ANSWER_KEY_JSON,
    BUILD_DIR,
    BUILT_ANSWER_KEY_JSON,
    BUILT_FACT_VOCABULARY_JSON,
    PACKAGE_ROOT,
    REPO_ROOT,
    SCENARIOS_DIR,
    TRIGGER_RULES,
)
from .answer_key import build_answer_key, load_answer_key, validate_answer_key
from .build import parse_all
from .fact_vocabulary import load_fact_vocabulary, validate_vocabulary

VOCAB_PATH = PACKAGE_ROOT / "packets" / "fact_vocabulary.yaml"


def build_main() -> int:
    packages = parse_all(SCENARIOS_DIR)
    vocabulary = load_fact_vocabulary(VOCAB_PATH) if VOCAB_PATH.exists() else None
    key = build_answer_key(packages, TRIGGER_RULES.read_text(encoding="utf-8"),
                           vocabulary=vocabulary)
    BUILD_DIR.mkdir(exist_ok=True)
    BUILT_ANSWER_KEY_JSON.write_text(key.to_json(), encoding="utf-8")

    for pid, pk in sorted(key.packets.items()):
        sets = " | ".join("{" + ", ".join(s) + "}" for s in
                          pk.minimal_criterion_satisfying_report_sets) or "-"
        print(f"{pid}: decision={pk.correct_decision}  minimal_sets={sets}")
        print(f"        noise={list(pk.noise_report_ids) or '-'}  "
              f"decoys={list(pk.decoy_report_ids) or '-'}")
    if vocabulary is not None:
        import json as _json
        packet_ids = {pid: p.report_ids
                      for pkg in packages.values() for pid, p in pkg.packets.items()}
        errors, warnings = validate_vocabulary(vocabulary, packet_ids)
        BUILT_FACT_VOCABULARY_JSON.write_text(
            _json.dumps(vocabulary.to_key_fragment(), indent=2, ensure_ascii=False),
            encoding="utf-8")
        status = "cleared" if vocabulary.is_reviewed else "DRAFT — NOT VALID FOR A SCORED RUN"
        print(f"fact vocabulary: {vocabulary.total_facts()} facts, "
              f"{len(errors)} error(s), {len(warnings)} warning(s) [{status}]")
        for e in errors:
            print(f"  ERROR {e.fact_id}: {e.message}")
        for wmsg in warnings:
            print(f"  warn  {wmsg.fact_id}: {wmsg.message}")

    print(f"trigger rules: {sorted(key.trigger_rules)}")
    print(f"wrote {BUILT_ANSWER_KEY_JSON.relative_to(REPO_ROOT)}")
    print(f"wrote {BUILT_FACT_VOCABULARY_JSON.relative_to(REPO_ROOT)}")
    return 0


def validate_main(*, check_hashes: bool = False) -> int:
    key_path = BUILT_ANSWER_KEY_JSON if BUILT_ANSWER_KEY_JSON.exists() else ANSWER_KEY_JSON
    if not key_path.exists():
        print(f"ERROR: {key_path} not found; run `sedition build-key` first")
        return 2

    key = load_answer_key(key_path)
    packages = parse_all(SCENARIOS_DIR)
    vocabulary = load_fact_vocabulary(VOCAB_PATH) if VOCAB_PATH.exists() else None
    errors = validate_answer_key(key, packages, check_hashes=check_hashes,
                                 vocabulary=vocabulary)

    checks = len(key.packets)
    if errors:
        print(f"FAIL: {len(errors)} error(s) across {checks} packets")
        for e in errors:
            print(f"  - {e}")
        return 1
    hash_note = " (hashes verified)" if check_hashes else ""
    print(f"OK: {checks} packets, 0 errors{hash_note}")
    if key.fact_vocabulary is None:
        print("note: the key carries no fact vocabulary — rebuild with `sedition build-key`")
    elif not key.fact_vocabulary.get("fact_vocabulary_reviewed"):
        print("note: the fact vocabulary is a DRAFT — scored runs are blocked until review")
    return 0
