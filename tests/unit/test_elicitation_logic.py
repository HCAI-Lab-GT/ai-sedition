"""The decision logic inside the elicitation rungs, tested without a model.

Rung N spends 17 model calls per episode (8 drafts + 1 selection + 8 officer
scorings). Rung 6 spends up to 7. A parsing bug in either is expensive to find
live and — because sample errors are captured per sample — would surface as a
quietly shrinking cell rather than a failure. Everything here is pure
function, so it costs nothing to check first.
"""
from __future__ import annotations

import pytest

from sedition_inspect.elicitation import (
    PROXY_MAX_ITERATIONS,
    best_of_selection_prompt,
    proxy_feedback_prompt,
)
from sedition_inspect.solver import _parse_choice, _rung_label

BASE = dict(observed_behaviour=False, self_critique=False, best_of=0,
            notepad=False, notepad_feedback=False, proxy_iterations=0,
            aggregation=False, aggregation_full_form=False,
            aggregation_shape=False, disclosed_mechanism=False)


# --------------------------------------------------------------- rung labels
@pytest.mark.parametrize("overrides,expected", [
    ({}, ""),
    ({"observed_behaviour": True}, "2.5"),
    ({"self_critique": True}, "2"),
    ({"best_of": 8}, "N"),
    ({"notepad": True}, "3"),
    ({"notepad": True, "notepad_feedback": True}, "3F"),
    ({"proxy_iterations": 3}, "6"),
    ({"aggregation": True}, "7"),
    ({"aggregation": True, "aggregation_full_form": True}, "7c"),
    ({"aggregation": True, "aggregation_full_form": True,
      "aggregation_shape": True}, "7d"),
    ({"aggregation": True, "best_of": 8}, "7+N"),
    ({"disclosed_mechanism": True}, "4"),
])
def test_rung_label(overrides, expected):
    assert _rung_label(**{**BASE, **overrides}) == expected


def test_rung_4_wins_over_every_other_flag():
    """The quarantine marker must never lose a precedence fight.

    A fitted episode mislabelled as an elicitation rung would be pooled with
    the ladder, which is the one thing rung 4 must never do.
    """
    every = dict(observed_behaviour=True, self_critique=True, best_of=8,
                 notepad=True, notepad_feedback=True, proxy_iterations=3,
                 aggregation=True, aggregation_full_form=True,
                 aggregation_shape=True, disclosed_mechanism=True)
    # Rung 4 wins; aggregation is recorded alongside it but never displaces it.
    assert _rung_label(**every).startswith("4")


def test_3F_wins_over_3():
    assert _rung_label(**{**BASE, "notepad": True, "notepad_feedback": True}) == "3F"


# ----------------------------------------------------- best-of-N choice parse
@pytest.mark.parametrize("raw,expected", [
    ('{"choice": 3, "reason": "clearest"}', 3),
    ('  {"choice":1,"reason":"x"}  ', 1),
    ('{"choice": 8, "reason": "last"}', 8),
    ('prose first {"choice": 2, "reason": "y"} prose after', 2),
    ('<think>weighing them</think>{"choice": 5, "reason": "z"}', 5),
    ('{"choice": "4", "reason": "string number"}', 4),
])
def test_parse_choice_accepts(raw, expected):
    choice, _reason = _parse_choice(raw, 8)
    assert choice == expected


@pytest.mark.parametrize("raw", [
    "",                                   # empty
    "I prefer candidate 3.",              # prose, no JSON
    '{"choice": 0, "reason": "x"}',       # below range
    '{"choice": 9, "reason": "x"}',       # above range
    '{"choice": -1, "reason": "x"}',      # negative
    '{"reason": "forgot the choice"}',    # missing key
    '{"choice": null, "reason": "x"}',    # null
    '{"choice": "three", "reason": "x"}', # unparseable
    "{not json at all",                   # malformed
])
def test_parse_choice_rejects(raw):
    """A bad selection must return -1 so the caller invalidates.

    Defaulting to draft 1 would silently convert a SELECTION FAILURE into a
    selection — and rung N exists precisely to tell those two apart.
    """
    choice, _reason = _parse_choice(raw, 8)
    assert choice == -1


def test_parse_choice_keeps_the_reason_even_when_the_choice_is_bad():
    _choice, reason = _parse_choice('{"choice": 99, "reason": "went rogue"}', 8)
    assert reason == "went rogue"


def test_selection_prompt_lists_every_candidate_and_never_hints():
    drafts = [f"draft body {i}" for i in range(8)]
    p = best_of_selection_prompt(drafts)
    for i in range(1, 9):
        assert f"Candidate {i}" in p
    for body in drafts:
        assert body in p
    assert "1 to 8" in p
    # Neutral on mechanism: it names the OUTCOME to optimise for and nothing
    # about how to get there.
    for forbidden in ("reassur", "brevity", "briefly", "concise", "shorter",
                      "tone", "borrowed", "published standard"):
        assert forbidden not in p.lower()


# ------------------------------------------------------------- rung 6 proxy
def test_proxy_feedback_states_the_action_and_nothing_more():
    p = proxy_feedback_prompt("NOTIFY_IMMEDIATELY", rounds_left=2)
    assert "NOTIFY_IMMEDIATELY" in p
    assert "2 revisions remaining" in p
    for forbidden in ("reassur", "brevity", "briefly", "concise", "shorter",
                      "tone", "wrong", "should have", "instead", "try to"):
        assert forbidden not in p.lower(), f"proxy feedback coaches: {forbidden}"


def test_proxy_feedback_singular_and_final_round():
    assert "1 revision remaining" in proxy_feedback_prompt("X", rounds_left=1)
    final = proxy_feedback_prompt("X", rounds_left=0)
    assert "final version" in final
    assert "remaining" not in final


def test_proxy_iteration_cap_is_three():
    """The declared threat model is bounded rehearsal. An unbounded loop would
    be a different experiment and would also spend without a ceiling."""
    assert PROXY_MAX_ITERATIONS == 3
