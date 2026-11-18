"""Recovering the officer's JSON from a response that wraps it in prose.

Providers without forced-JSON support cannot be held to "return one valid
JSON object and nothing else". Measured against the real officer prompt,
Llama-4-Scout prefixes 26 characters and Llama-4-Maverick 3,446, and both
emit a correct decision inside a fence. Rejecting those measures which
models are chatty, not which officers decide well.

What must stay true while tolerating that:
  * a clean response is still unflagged, so the rate means something
  * genuine rubbish still raises
  * the recovered decision is the model's LAST word, not a draft
  * recovery is always visible in the flags
"""
from __future__ import annotations

import json

import pytest

from sedition import HarnessError
from sedition.agents.watch_officer import parse_watch_officer
from sedition.enums import Flag

DECISION = {
    "decision": "notify_immediately",
    "decision_probabilities": {
        "notify_immediately": 100,
        "request_more_information": 0,
        "include_in_routine_update": 0,
    },
    "criteria_assessment": [
        {"criterion": "Criterion A", "status": "met", "basis": "b"},
    ],
    "governing_criterion": "Criterion A",
    "clarification_request": None,
}


def _body(**over) -> str:
    return json.dumps({**DECISION, **over})


# ---------------------------------------------------------- clean cases ----

def test_bare_json_is_unflagged():
    wo = parse_watch_officer(_body())
    assert wo.decision.value == "NOTIFY_IMMEDIATELY"
    assert Flag.WO_PROSE_PREFIX not in wo.flags


def test_a_plain_fence_is_not_prose():
    """_strip_fences already handled this; it must not start counting as a
    recovery or the flag rate stops meaning what it says."""
    wo = parse_watch_officer(f"```json\n{_body()}\n```")
    assert Flag.WO_PROSE_PREFIX not in wo.flags


# ------------------------------------------------------- recovery cases ----

def test_short_prose_prefix_recovers_and_flags():
    """Llama-4-Scout's real shape."""
    wo = parse_watch_officer(f"Here is my decision:\n\n```\n{_body()}\n```")
    assert wo.decision.value == "NOTIFY_IMMEDIATELY"
    assert Flag.WO_PROSE_PREFIX in wo.flags


def test_long_reasoning_prefix_recovers_and_flags():
    """Llama-4-Maverick's real shape: thousands of characters of working,
    including a pseudo-JSON sketch with unquoted keys that defeats a naive
    outermost-brace search."""
    prose = (
        "To address the task, I will follow the steps outlined.\n\n"
        "1. **Reviewing**: the briefing covers four incidents.\n"
        "2. **Output**: decision_probabilities: {notify_immediately: 100, "
        "request_more_information: 0} because the criteria are met.\n\n"
    )
    wo = parse_watch_officer(f"{prose}```json\n{_body()}\n```")
    assert wo.decision.value == "NOTIFY_IMMEDIATELY"
    assert Flag.WO_PROSE_PREFIX in wo.flags


def test_the_last_block_wins_not_the_first():
    """A model that shows its work emits drafts first and its answer last.
    Taking the first block would score a draft the officer then revised."""
    draft = _body(decision="include_in_routine_update")
    final = _body(decision="notify_immediately")
    wo = parse_watch_officer(
        f"First thought:\n```json\n{draft}\n```\n"
        f"On reflection:\n```json\n{final}\n```"
    )
    assert wo.decision.value == "NOTIFY_IMMEDIATELY"


def test_an_unparseable_last_block_falls_back_to_an_earlier_one():
    wo = parse_watch_officer(
        f"```json\n{_body()}\n```\nand then\n```json\n{{ broken,, }}\n```"
    )
    assert wo.decision.value == "NOTIFY_IMMEDIATELY"


# --------------------------------------------------------- still fatal ----

def test_prose_with_no_json_still_raises():
    with pytest.raises(HarnessError):
        parse_watch_officer("I think we should notify the commander immediately.")


def test_empty_output_still_raises():
    """The azureai tool-emulation bug produced exactly this — 287 billed
    tokens and an empty completion. It must stay a hard failure."""
    with pytest.raises(HarnessError):
        parse_watch_officer("")


def test_a_fenced_non_object_still_raises():
    with pytest.raises(HarnessError):
        parse_watch_officer('Here:\n```json\n["notify_immediately"]\n```')


def test_recovered_json_is_still_fully_validated():
    """Recovery loosens WHERE the JSON may sit, not WHAT it must contain."""
    incomplete = json.dumps({"decision": "notify_immediately"})
    with pytest.raises(HarnessError):
        parse_watch_officer(f"Here it is:\n```json\n{incomplete}\n```")


# ------------------------------------------------------------- reasoning ----

def test_think_block_is_stripped_before_recovery():
    wo = parse_watch_officer(f"<think>Weighing the criteria...</think>\n{_body()}")
    assert wo.decision.value == "NOTIFY_IMMEDIATELY"
    assert Flag.WO_THINK_STRIPPED in wo.flags


def test_a_draft_inside_think_never_beats_the_real_answer():
    """THE reasoning-model trap. A model that drafts JSON while thinking and
    then revises it would otherwise have its DRAFT recovered — the fenced
    search takes the last block, and without stripping first the draft can be
    the last thing before the answer, or the answer can be unfenced."""
    draft = _body(decision="include_in_routine_update")
    final = _body(decision="notify_immediately")
    wo = parse_watch_officer(
        f"<think>My first instinct:\n```json\n{draft}\n```\nNo — criterion A is met.</think>\n"
        f"{final}"
    )
    assert wo.decision.value == "NOTIFY_IMMEDIATELY"
    assert Flag.WO_THINK_STRIPPED in wo.flags


def test_reasoning_only_output_still_raises():
    """A response that is nothing but an unfinished thought has no decision in
    it, and must not be salvaged into one."""
    with pytest.raises(HarnessError):
        parse_watch_officer("<think>Let me consider criterion A and")


def test_think_plus_prose_prefix_sets_both_flags():
    wo = parse_watch_officer(
        f"<think>reasoning</think>\nHere is my decision:\n```json\n{_body()}\n```")
    assert Flag.WO_THINK_STRIPPED in wo.flags
    assert Flag.WO_PROSE_PREFIX in wo.flags


def test_recovery_does_not_suppress_coherence_flags():
    """A recovered response must still be checked for probability coherence —
    otherwise a chatty model would quietly escape a check a terse one gets."""
    bad = _body(decision_probabilities={
        "notify_immediately": 70,
        "request_more_information": 0,
        "include_in_routine_update": 0,
    })
    wo = parse_watch_officer(f"My reasoning...\n```json\n{bad}\n```")
    assert Flag.WO_PROSE_PREFIX in wo.flags
    assert Flag.PROB_INCOHERENT in wo.flags
