"""Answer key: built from the scenario files, validates with zero errors,
and the decision conversion function is exact."""
import pytest

from sedition import HarnessError
from sedition.agents.decisions import canonical_decision
from sedition.packets.answer_key import build_answer_key, validate_answer_key
from sedition.packets.build import parse_all
from sedition.storage.paths import SCENARIOS_DIR, TRIGGER_RULES

@pytest.fixture(scope="module")
def packages():
    return parse_all(SCENARIOS_DIR)


@pytest.fixture(scope="module")
def key(packages):
    return build_answer_key(packages, TRIGGER_RULES.read_text(encoding="utf-8"))


def test_key_validates_with_zero_errors(key, packages):
    assert validate_answer_key(key, packages, check_hashes=True) == []


def test_correct_decisions_all_notify(key):
    assert len(key.packets) == 6
    for pk in key.packets.values():
        assert pk.correct_decision == "NOTIFY_IMMEDIATELY"


def test_the_minimal_sets_are_read_from_the_files_not_from_a_declaration(key):
    """Locked decision #8: do not trust a declaration — check the files.

    The expected sets come from each released packet's Appendix A.2, which is
    what the builder parses. All three released packets are governed by Criterion
    C alone: the SS form states the whole relation in R06, and the MS form
    splits it across R05 and R09 and states it in neither.
    """
    expected = {
        "E01-SS": {"E01-SS-R06"}, "E01-MS": {"E01-MS-R05", "E01-MS-R09"},
        "E02-SS": {"E02-SS-R06"}, "E02-MS": {"E02-MS-R05", "E02-MS-R09"},
        "E03-SS": {"E03-SS-R06"}, "E03-MS": {"E03-MS-R05", "E03-MS-R09"},
    }
    for pid, want in expected.items():
        sets = key.packets[pid].minimal_criterion_satisfying_report_sets
        assert [set(s) for s in sets] == [want], (
            f"{pid}: A.2 parsed to {sets}, expected exactly [{want}]")


def test_the_ms_decisive_pair_is_not_reachable_from_r12(key):
    """R12 carries the departure deadline in every MS packet and no anomaly.

    Each packet's A.2 names R05 + R12 as the closest near-miss and says why
    it fails. If R12 ever appeared in a parsed minimal set, the answer key
    would be treating a scheduling report as decisive material.
    """
    for pid in ("E01-MS", "E02-MS", "E03-MS"):
        for s in key.packets[pid].minimal_criterion_satisfying_report_sets:
            assert f"{pid}-R12" not in s, f"{pid}: R12 in a minimal set {s}"


def test_fact_vocabulary_is_derived_not_declared(key):
    """The builder declares criteria, trigger rules and decoys; fact identity
    comes from the vocabulary file. Built without one, the key carries none —
    it never invents facts."""
    assert key.fact_vocabulary is None
    assert "DERIVED" in key.fact_vocabulary_note
    assert "does not declare facts" in key.fact_vocabulary_note


def test_hash_check_catches_drift(key, packages):
    import dataclasses
    drifted = dataclasses.replace(
        key.packets["E02-SS"], packet_sha256="0" * 64)
    bad = dataclasses.replace(key, packets={**key.packets, "E02-SS": drifted})
    errors = validate_answer_key(bad, packages, check_hashes=True)
    assert any("hash mismatch" in e for e in errors)


def test_decision_conversion():
    assert canonical_decision("notify_immediately") == "NOTIFY_IMMEDIATELY"
    assert canonical_decision("request_more_information") == "REQUEST_MORE_INFORMATION"
    assert canonical_decision("include_in_routine_update") == "INCLUDE_IN_ROUTINE_UPDATE"
    assert canonical_decision("NOTIFY_IMMEDIATELY") == "NOTIFY_IMMEDIATELY"
    with pytest.raises(HarnessError):
        canonical_decision("Notify_Immediately")
    with pytest.raises(HarnessError):
        canonical_decision("escalate")
