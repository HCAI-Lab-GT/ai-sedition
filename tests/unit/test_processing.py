"""Stripping: one test per compliance flag this module can raise, plus the
redaction gate. The end-to-end chokepoint guarantees live in
test_strip_chokepoint.py; this file is the unit-level coverage.

Note the recipient-specific design: the monitor legitimately receives the
visible notification standard, including the word "criterion" in prose. Only
the watch officer's *structured* criterion / criteria_assessment / basis
fields are stripped, and only from the analyst-bound clarification payload.
"""
import pytest

from sedition import PrivacyLeakError
from sedition.enums import Cell, Continuation, Flag, Turn
from sedition.pipeline.redact import (
    analyst_clarification_input,
    redact_for_monitor,
    redact_for_watch_officer,
)
from sedition.pipeline.strip import strip_analyst_output, word_count

SHEET_BLOCK = (
    "=== WORKING SHEET ===\n"
    "REPORTS\nE01-SS-R01 | closed | nothing notable | lacks: none stated\n\n"
    "LINKS\nnone\n\n"
    "COMPARISONS\nnone\n\n"
    "GROUPS\nG1 | E01-SS-R01 | routine item\n"
    "=== END WORKING SHEET ==="
)
BRIEFING = "=== INCIDENT ===\nIncident title: x\nSummary: y."
SHEET_RESPONSE = f"{SHEET_BLOCK}\n\n{BRIEFING}"


# ---------------------------------------------------------- happy path ----

def test_straight_condition_passes_through_unmodified():
    result = strip_analyst_output(BRIEFING, turn=Turn.INITIAL, cell=Cell.HONEST_STRAIGHT)
    assert result.valid
    assert result.working_sheet is None
    assert result.artifact == BRIEFING
    assert result.flags == frozenset()


def test_sheet_initial_turn_extracts_private_block_and_public_briefing():
    result = strip_analyst_output(SHEET_RESPONSE, turn=Turn.INITIAL, cell=Cell.HONEST_SHEET)
    assert result.valid
    assert result.working_sheet == SHEET_BLOCK
    assert result.artifact == BRIEFING
    assert "=== WORKING SHEET ===" not in result.artifact
    assert result.flags == frozenset()


def test_sheet_clarification_turn_extracts_check_block():
    raw = ("=== CLARIFICATION CHECK ===\n"
           "weight discrepancy | [E03-SS-R06] | confirmed as stated\n"
           "=== END CLARIFICATION CHECK ===\n\n"
           "The measured weight was 12,469 pounds. [E03-SS-R06]")
    result = strip_analyst_output(raw, turn=Turn.CLARIFICATION, cell=Cell.HONEST_SHEET)
    assert result.valid
    assert result.clarification_check.startswith("=== CLARIFICATION CHECK ===")
    assert result.artifact == "The measured weight was 12,469 pounds. [E03-SS-R06]"


def test_strategic_continuation_line_stripped_before_private_block():
    raw = ("CONTINUATION: ABANDON\n\n"
           "=== CLARIFICATION CHECK ===\nx | [E01-SS-R01] | ok\n=== END CLARIFICATION CHECK ===\n\n"
           "The figures differ by 12 units. [E01-SS-R01]")
    result = strip_analyst_output(raw, turn=Turn.CLARIFICATION, cell=Cell.STRATEGIC_SHEET)
    assert result.continuation is Continuation.ABANDON
    assert result.valid
    assert "CONTINUATION" not in result.artifact
    assert "CONTINUATION" not in result.clarification_check


# --------------------------------------------------- one test per flag ----

def test_flag_sheet_malformed_on_missing_opening_marker():
    raw = f"REPORTS\nnone\n=== END WORKING SHEET ===\n\n{BRIEFING}"
    result = strip_analyst_output(raw, turn=Turn.INITIAL, cell=Cell.HONEST_SHEET)
    assert not result.valid
    assert result.artifact == ""
    assert Flag.SHEET_MALFORMED in result.flags


def test_flag_sheet_malformed_on_duplicated_marker():
    raw = f"{SHEET_RESPONSE}\n{SHEET_BLOCK}"
    result = strip_analyst_output(raw, turn=Turn.INITIAL, cell=Cell.HONEST_SHEET)
    assert not result.valid
    assert Flag.SHEET_MALFORMED in result.flags


def test_flag_sheet_malformed_on_reversed_markers():
    raw = f"=== END WORKING SHEET ===\nstray\n=== WORKING SHEET ===\n\n{BRIEFING}"
    result = strip_analyst_output(raw, turn=Turn.INITIAL, cell=Cell.HONEST_SHEET)
    assert not result.valid
    assert Flag.SHEET_MALFORMED in result.flags


def test_flag_sheet_malformed_on_missing_required_heading():
    raw = ("=== WORKING SHEET ===\nREPORTS\nnone\n\nCOMPARISONS\nnone\n\nGROUPS\nnone\n"
           f"=== END WORKING SHEET ===\n\n{BRIEFING}")  # LINKS absent
    result = strip_analyst_output(raw, turn=Turn.INITIAL, cell=Cell.HONEST_SHEET)
    assert not result.valid
    assert Flag.SHEET_MALFORMED in result.flags


def test_flag_sheet_malformed_on_out_of_order_headings():
    raw = ("=== WORKING SHEET ===\nREPORTS\nnone\n\nCOMPARISONS\nnone\n\nLINKS\nnone\n\nGROUPS\nnone\n"
           f"=== END WORKING SHEET ===\n\n{BRIEFING}")
    result = strip_analyst_output(raw, turn=Turn.INITIAL, cell=Cell.HONEST_SHEET)
    assert not result.valid
    assert Flag.SHEET_MALFORMED in result.flags


def test_flag_sheet_malformed_when_followed_by_no_public_output():
    result = strip_analyst_output(SHEET_BLOCK, turn=Turn.INITIAL, cell=Cell.HONEST_SHEET)
    assert not result.valid
    assert Flag.SHEET_MALFORMED in result.flags


def test_flag_clarification_check_malformed_on_unbalanced_markers():
    raw = "=== CLARIFICATION CHECK ===\nsome check\n\nanswer text"  # no closing marker
    result = strip_analyst_output(raw, turn=Turn.CLARIFICATION, cell=Cell.HONEST_SHEET)
    assert not result.valid
    assert Flag.CLARIFICATION_CHECK_MALFORMED in result.flags


def test_flag_prompt_assembly_failure_when_private_marker_appears_in_straight():
    result = strip_analyst_output(SHEET_RESPONSE, turn=Turn.INITIAL, cell=Cell.HONEST_STRAIGHT)
    assert not result.valid
    assert Flag.PROMPT_ASSEMBLY_FAILURE in result.flags
    assert Flag.SHEET_LEAK in result.flags
    assert result.artifact == ""


def test_flag_continuation_undeclared_when_expected_but_absent():
    raw = ("=== CLARIFICATION CHECK ===\nx | [E01-SS-R01] | ok\n=== END CLARIFICATION CHECK ===\n\n"
           "answer text")
    result = strip_analyst_output(raw, turn=Turn.CLARIFICATION, cell=Cell.STRATEGIC_SHEET)
    assert result.continuation is Continuation.UNDECLARED
    assert Flag.CONTINUATION_UNDECLARED in result.flags
    # soft flag: the episode remains valid and is still analyzed
    assert result.valid


def test_continuation_not_expected_for_non_strategic_policies():
    raw = ("=== CLARIFICATION CHECK ===\nx | [E01-SS-R01] | ok\n=== END CLARIFICATION CHECK ===\n\n"
           "answer text")
    result = strip_analyst_output(raw, turn=Turn.CLARIFICATION, cell=Cell.BASIC_SHEET)
    assert result.continuation is None
    assert result.flags == frozenset()


def test_malformed_continuation_value_is_undeclared():
    raw = f"CONTINUATION: MAYBE\n\n{SHEET_RESPONSE}"
    result = strip_analyst_output(raw, turn=Turn.CLARIFICATION, cell=Cell.STRATEGIC_SHEET)
    assert result.continuation is Continuation.UNDECLARED
    assert Flag.CONTINUATION_UNDECLARED in result.flags


# ------------------------------------------------------------ redaction ---

def test_redaction_passes_faithful_artifact_through():
    for builder in (redact_for_watch_officer, redact_for_monitor):
        payload = builder(BRIEFING)
        assert payload.text == BRIEFING


def test_redaction_rejects_leaked_private_material():
    for builder in (redact_for_watch_officer, redact_for_monitor):
        with pytest.raises(PrivacyLeakError):
            builder(SHEET_RESPONSE)
        with pytest.raises(PrivacyLeakError):
            builder("CONTINUATION: CONTINUE\n\nanswer")


def test_monitor_keeps_visible_notification_standard_including_the_word_criterion():
    text = "Briefing referencing IMMEDIATE NOTIFICATION CRITERIA. Criterion A concerns access control."
    assert "Criterion A" in redact_for_monitor(text).text


def test_analyst_clarification_input_strips_exactly_the_structured_fields():
    wo_request = {
        "criterion": "B", "criteria_assessment": {"A": "unmet"}, "basis": "para 2",
        "fact_needed": "whether the two measurements agree",
        "report_ids": ["E02-MS-R02", "E02-MS-R09"],
    }
    payload = analyst_clarification_input(wo_request)
    assert set(payload) == {"fact_needed", "report_ids"}
    assert payload["report_ids"] == wo_request["report_ids"]


def test_word_count():
    assert word_count("one two three") == 3
    assert word_count("") == 0
