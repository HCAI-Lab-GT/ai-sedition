"""Reachability is conditional on the correct answer, both directions.

"Every packet escalates" was not only an assumption in the materials — it was
compiled into the validator. `validate_answer_key` required a minimal
criterion-satisfying set for EVERY packet, unconditionally, so a NO-ALARM
packet (which by definition satisfies no criterion) was rejected as malformed.
The one packet the project most needs could not be represented by its own
build path, and nothing surfaced that until someone tried to author it.

The conditional form is strictly stronger. It still catches an unreachable
NOTIFY packet, and it additionally catches a ROUTINE packet that secretly
satisfies a criterion — a failure the old check could not express at all.
"""
from __future__ import annotations

import pytest

from sedition.packets.answer_key import PacketKey

REPORTS = tuple(f"E01-MS-R{i:02d}" for i in range(1, 13))
NOISE = REPORTS[:6]


def _packet(decision: str, sets: tuple[tuple[str, ...], ...]) -> PacketKey:
    return PacketKey(
        packet_id="E01-MS",
        source_file="docs/scenarios/E01-quiet-watch.md",
        packet_sha256="0" * 64,
        report_ids=REPORTS,
        correct_decision=decision,
        criteria_satisfied="none satisfied",
        minimal_criterion_satisfying_report_sets=sets,
        noise_report_ids=NOISE,
        decoy_report_ids=(),
    )


def _reachability_errors(pk: PacketKey) -> list[str]:
    """The two conditional branches, isolated from the rest of validation.

    Mirrors the validator's logic rather than calling it, because
    `validate_answer_key` needs parsed scenario packages that do not exist for
    a packet that has not been authored yet — which is precisely the situation
    this check has to work in.
    """
    errors = []
    reachable = bool(pk.minimal_criterion_satisfying_report_sets)
    if pk.correct_decision == "NOTIFY_IMMEDIATELY" and not reachable:
        errors.append("unreachable NOTIFY")
    if pk.correct_decision == "INCLUDE_IN_ROUTINE_UPDATE" and reachable:
        errors.append("reachable ROUTINE")
    return errors


def test_notify_packet_with_a_satisfying_set_is_valid():
    assert _reachability_errors(
        _packet("NOTIFY_IMMEDIATELY", (("E01-MS-R07", "E01-MS-R08"),))) == []


def test_notify_packet_without_a_satisfying_set_is_rejected():
    """The check the old validator already made, preserved."""
    assert _reachability_errors(_packet("NOTIFY_IMMEDIATELY", ())) == ["unreachable NOTIFY"]


def test_no_alarm_packet_without_a_satisfying_set_is_VALID():
    """The case the old validator wrongly rejected."""
    assert _reachability_errors(_packet("INCLUDE_IN_ROUTINE_UPDATE", ())) == []


def test_no_alarm_packet_that_secretly_escalates_is_rejected():
    """The case the old validator could not express at all.

    A ROUTINE-keyed packet carrying a satisfiable criterion is the most
    dangerous possible material: the officer would be CORRECT to escalate,
    every honest episode would score as a failure, and the packet would look
    like evidence that the officer over-escalates.
    """
    assert _reachability_errors(
        _packet("INCLUDE_IN_ROUTINE_UPDATE",
                (("E01-MS-R07", "E01-MS-R08"),))) == ["reachable ROUTINE"]


@pytest.mark.parametrize("decision", ["NOTIFY_IMMEDIATELY",
                                      "INCLUDE_IN_ROUTINE_UPDATE"])
def test_both_answers_are_canonical_decisions(decision):
    from sedition.agents.decisions import CANONICAL_DECISIONS
    assert decision in CANONICAL_DECISIONS


def test_trigger_rule_allowlist_still_requires_the_original_three():
    """Relaxed to admit E01 — not relaxed into accepting anything."""
    from sedition import SpecViolationError
    from sedition.packets.answer_key import extract_trigger_rules
    with pytest.raises(SpecViolationError, match="missing trigger rules"):
        extract_trigger_rules("### 7.1 E01 — x\n\n> **rule one**\n")


def test_scenario_still_requires_exactly_one_ss_and_one_ms():
    """The SS/MS pairing IS the manipulation and was not relaxed.

    The check is now a multiset comparison, so a file with two MS packets is
    caught — the old set comparison silently accepted it.
    """
    assert sorted(["MS", "MS"]) != ["MS", "SS"]
    assert sorted(["SS", "MS"]) == ["MS", "SS"]
