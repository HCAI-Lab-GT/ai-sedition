"""An escalation's basis must be a reported field, on both officer turns.

WHY THIS EXISTS. In the ablated-twin column a criterion firing can mean either
of two opposite things: the twin's resolution did not persuade the officer, or
the criterion genuinely survives resolution. Nothing in the decision, the
probabilities, or the criterion status separates those. Only the officer's
stated `basis` does.

Round 1 has recorded `basis` since it was made first-class. The FINAL turn did
NOT -- it stored `wo_final_decision` and `wo_final_probabilities` and dropped
`criteria_assessment` entirely. So for any episode that went through
clarification, the reasoning behind the DECISION OF RECORD was recoverable only
from raw model output via attachment refs, which does not scale.

THE CONTRACT:
  * both officer turns record criterion / status / basis;
  * the store carries a field for each turn, so neither is derived from the
    other;
  * `final_decision` (the decision of record) and the basis for it come from
    the same turn.

These are unit tests over the parse and store layers. They do NOT prove the
solver assigns the field on a live episode -- `test_the_solver_assigns_the_final
_criteria_field` pins that by reading the source, which is weaker than a run but
catches the exact regression that occurred (an assignment silently absent).
"""
from __future__ import annotations

import inspect
import json
import re

import pytest

from sedition.agents.watch_officer import parse_watch_officer
from sedition.enums import CriterionStatus, Decision
from sedition_inspect._store import EpisodePublic

CRITERIA = [
    {"criterion": "Criterion A", "status": "not_met", "basis": "No second sample."},
    {"criterion": "Criterion B", "status": "not_met", "basis": "Reconciled by TO-118."},
    {"criterion": "Criterion C", "status": "met",
     "basis": "R11 leaves the port cover unexplained and R12 loads at 0415K."},
]


def _resp(decision="notify_immediately", criteria=None, turn="DECISION"):
    probs = {"notify_immediately": 100, "request_more_information": 0,
             "include_in_routine_update": 0}
    if decision == "include_in_routine_update":
        probs = {"notify_immediately": 0, "request_more_information": 0,
                 "include_in_routine_update": 100}
    return json.dumps({"decision": decision, "decision_probabilities": probs,
                       "criteria_assessment": CRITERIA if criteria is None else criteria})


@pytest.mark.parametrize("turn", ["DECISION", "FINAL"])
def test_the_basis_survives_parsing_on_both_turns(turn):
    out = parse_watch_officer(_resp(turn=turn), turn=turn)
    met = [c for c in out.criteria_assessment if c.status is CriterionStatus.MET]
    assert met, "fixture no longer escalates; the test would pass vacuously"
    for c in met:
        assert c.basis.strip(), f"{turn}: criterion {c.criterion} escalated with no basis"


@pytest.mark.parametrize("turn", ["DECISION", "FINAL"])
def test_the_basis_reaches_the_serialised_form(turn):
    """to_dict() is what the log carries. A basis held only on the dataclass is
    not a reported field."""
    d = parse_watch_officer(_resp(turn=turn), turn=turn).to_dict()
    bases = [c["basis"] for c in d["criteria_assessment"]]
    assert all(isinstance(b, str) for b in bases)
    assert any(b.strip() for b in bases), f"{turn}: no basis in the serialised output"


def test_the_store_carries_a_criteria_field_for_each_turn():
    """Round 1 and FINAL need separate fields. One field shared between them
    cannot say which turn a basis came from, and the decision of record may be
    either turn."""
    fields = EpisodePublic.model_fields
    for name in ("wo_criteria", "wo_final_criteria"):
        assert name in fields, f"{name} is not a store field"
    s = EpisodePublic()
    assert s.wo_criteria == []
    assert s.wo_final_criteria == []


def test_the_two_turn_fields_are_independent():
    """Setting one must not move the other -- otherwise a clarification episode
    would report round 1's reasoning against the FINAL decision."""
    s = EpisodePublic()
    s.wo_criteria = [{"criterion": "Criterion C", "status": "met", "basis": "round one"}]
    s.wo_final_criteria = [{"criterion": "Criterion C", "status": "not_met",
                            "basis": "the located authorization answers it"}]
    assert s.wo_criteria[0]["basis"] == "round one"
    assert s.wo_final_criteria[0]["basis"] == "the located authorization answers it"


def test_the_decision_of_record_has_a_basis_from_its_own_turn():
    """`final_decision` prefers the FINAL turn. The basis reported alongside it
    must come from that same turn, which is only possible if FINAL carries its
    own criteria."""
    s = EpisodePublic()
    s.wo_decision = Decision.NOTIFY_IMMEDIATELY.value
    s.wo_criteria = [{"criterion": "Criterion C", "status": "met", "basis": "round one"}]
    s.wo_final_decision = Decision.INCLUDE_IN_ROUTINE_UPDATE.value
    s.wo_final_criteria = [{"criterion": "Criterion C", "status": "not_met",
                            "basis": "resolved on the clarification"}]
    assert s.final_decision == Decision.INCLUDE_IN_ROUTINE_UPDATE.value
    basis = (s.wo_final_criteria if s.wo_final_decision else s.wo_criteria)
    assert basis[0]["basis"] == "resolved on the clarification"


def test_the_solver_assigns_the_final_criteria_field():
    """The regression was an assignment that was simply absent: the FINAL turn
    stored a decision and probabilities and dropped the assessment. Nothing else
    in this file would catch that, because every other test constructs the store
    directly."""
    from sedition_inspect import solver

    src = inspect.getsource(solver)
    assert re.search(r"public\.wo_final_criteria\s*=", src), (
        "the solver never assigns wo_final_criteria -- the FINAL turn's basis is "
        "being dropped again")
    # And it must be built from the FINAL turn's output, not round 1's.
    m = re.search(r"public\.wo_final_criteria\s*=\s*\[(.{0,220})", src, re.S)
    assert m and "wo_final.criteria_assessment" in m.group(1), (
        "wo_final_criteria is not populated from wo_final.criteria_assessment")


def test_an_escalation_with_an_empty_basis_is_visible_not_silent():
    """A model may return an empty basis. That must remain readable in the record
    rather than being dropped to an absent field -- 'the officer gave no reason'
    and 'we did not record the reason' are different findings."""
    crit = [{"criterion": "Criterion C", "status": "met", "basis": ""}]
    out = parse_watch_officer(_resp(criteria=crit), turn="DECISION")
    assert out.criteria_assessment[0].status is CriterionStatus.MET
    assert out.criteria_assessment[0].basis == ""
    assert "basis" in out.to_dict()["criteria_assessment"][0]


def test_a_missing_basis_key_does_not_lose_the_criterion():
    crit = [{"criterion": "Criterion C", "status": "met"}]
    out = parse_watch_officer(_resp(criteria=crit), turn="DECISION")
    assert len(out.criteria_assessment) == 1
    assert out.criteria_assessment[0].basis == ""
