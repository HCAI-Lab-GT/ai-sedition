"""An unusable probability vector must not cost us the categorical decision.

WHY THIS EXISTS. These are two channels and only one of them is the experiment.
The categorical decision -- notify / routine / request-more-info -- is the
outcome measure. The probability vector is a secondary diagnostic. Treating a
malformed diagnostic as fatal to the whole episode throws away the measurement
to protect a footnote.

Measured, not hypothetical: on OpenRouter DeepSeek-V3.2 as watch officer,
**56 of 60 first responses carried a sentinel probability (93.3%)**, and under
fatal treatment that discarded **42 of 60 readable categorical decisions (70%)**.
See PREREGISTRATION 71. `null` additionally raised an unhandled TypeError, so an
episode could die on a field nothing downstream required.

THE CONTRACT, per that section:
  * an unusable probability preserves the categorical decision;
  * the vector is flagged PROB_INCOHERENT;
  * probability-specific analysis excludes flagged vectors;
  * it does NOT trigger a re-prompt -- re-prompting to repair a diagnostic would
    change what the officer saw, which is a worse problem than the missing
    diagnostic;
  * bounded format correction remains only for STRUCTURALLY unusable output --
    output that cannot be parsed into a decision at all.
"""
from __future__ import annotations

import json

import pytest

from sedition.agents.watch_officer import parse_watch_officer
from sedition.enums import Decision, Flag

_CRITERIA = [{"criterion": f"Criterion {c}", "status": "not_met", "basis": "x"}
             for c in "ABC"]

#: Every shape a model has produced, or plausibly could, in place of a number.
UNUSABLE = {
    "sentinel_minus_one_all": {"notify_immediately": -1, "request_more_information": -1,
                               "include_in_routine_update": -1},
    "sentinel_minus_one_one": {"notify_immediately": -1, "request_more_information": 0,
                               "include_in_routine_update": 100},
    "null": {"notify_immediately": None, "request_more_information": 0,
             "include_in_routine_update": 100},
    "string": {"notify_immediately": "unknown", "request_more_information": 0,
               "include_in_routine_update": 100},
    "above_one_hundred": {"notify_immediately": 150, "request_more_information": 0,
                          "include_in_routine_update": -50},
    "does_not_sum": {"notify_immediately": 10, "request_more_information": 0,
                     "include_in_routine_update": 80},
}


def _resp(probs, decision="include_in_routine_update"):
    return json.dumps({"decision": decision, "decision_probabilities": probs,
                       "criteria_assessment": _CRITERIA})


def test_the_unusable_table_is_populated():
    """Anti-vacuity: the parametrised tests below would all pass on an empty table."""
    assert len(UNUSABLE) >= 6


@pytest.mark.parametrize("name", sorted(UNUSABLE))
def test_an_unusable_vector_preserves_the_decision(name):
    out = parse_watch_officer(_resp(UNUSABLE[name]), turn="DECISION")
    assert out.decision is Decision.INCLUDE_IN_ROUTINE_UPDATE, (
        f"{name}: the categorical decision was lost to a malformed probability")


@pytest.mark.parametrize("name", sorted(UNUSABLE))
def test_an_unusable_vector_is_flagged(name):
    out = parse_watch_officer(_resp(UNUSABLE[name]), turn="DECISION")
    assert Flag.PROB_INCOHERENT in out.flags, f"{name}: not flagged"


@pytest.mark.parametrize("name", sorted(UNUSABLE))
def test_an_unusable_vector_never_raises(name):
    """`null` used to raise TypeError here. An episode must not die on a
    secondary field."""
    parse_watch_officer(_resp(UNUSABLE[name]), turn="DECISION")


@pytest.mark.parametrize("name", sorted(UNUSABLE))
def test_an_unusable_entry_can_never_win_the_argmax(name):
    """The recorded decision must come from the officer, never from a sentinel
    that happened to sort highest."""
    out = parse_watch_officer(_resp(UNUSABLE[name], decision="notify_immediately"),
                              turn="DECISION")
    assert out.decision is Decision.NOTIFY_IMMEDIATELY


def test_a_coherent_vector_is_not_flagged():
    """The guard must not fire on healthy output, or it means nothing."""
    out = parse_watch_officer(_resp({"notify_immediately": 10,
                                     "request_more_information": 10,
                                     "include_in_routine_update": 80}), turn="DECISION")
    assert Flag.PROB_INCOHERENT not in out.flags
    assert out.decision is Decision.INCLUDE_IN_ROUTINE_UPDATE


def test_structurally_unusable_output_still_raises():
    """The separation is about a bad PROBABILITY, not a bad response. Output
    carrying no decision at all is structurally unusable and must still fail --
    that is where bounded format correction belongs."""
    from sedition import HarnessError
    with pytest.raises((HarnessError, KeyError, ValueError)):
        parse_watch_officer(json.dumps({"criteria_assessment": _CRITERIA}), turn="DECISION")
