"""The threshold is applied in code, not by the model that assessed the criteria.

These tests pin the arithmetic the split architecture depends on: one
assessment must yield the same criterion statuses at every threshold, and an
assessment the function cannot interpret must fail loudly rather than default
to a decision.
"""

import pytest

from sedition.scoring.threshold_rule import (
    NOTIFY,
    ROUTINE,
    count_met,
    decide,
)


def assessment(*statuses: str) -> list[dict[str, str]]:
    return [
        {"criterion": f"Criterion {chr(65 + i)}", "status": s}
        for i, s in enumerate(statuses)
    ]


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (("met", "met", "met"), 3),
        (("met", "not_met", "met"), 2),
        (("not_met", "not_met", "not_met"), 0),
        (("met", "uncertain", "not_met"), 1),
        (("uncertain", "uncertain", "uncertain"), 0),
        (("MET", " Met ", "not_met"), 2),
    ],
)
def test_count_met(statuses: tuple[str, ...], expected: int) -> None:
    assert count_met(assessment(*statuses)) == expected


def test_uncertain_does_not_count_toward_the_threshold() -> None:
    """Mirrors watch_officer section 9.3, so the two architectures share a rule."""
    a = assessment("met", "uncertain", "uncertain")
    assert count_met(a) == 1
    assert decide(a, 1) == NOTIFY
    assert decide(a, 2) == ROUTINE


@pytest.mark.parametrize(
    "statuses,k,expected",
    [
        (("met", "not_met", "not_met"), 1, NOTIFY),
        (("met", "not_met", "not_met"), 2, ROUTINE),
        (("met", "met", "not_met"), 2, NOTIFY),
        (("met", "met", "not_met"), 3, ROUTINE),
        (("met", "met", "met"), 3, NOTIFY),
        (("not_met", "not_met", "not_met"), 1, ROUTINE),
    ],
)
def test_decide(statuses: tuple[str, ...], k: int, expected: str) -> None:
    assert decide(assessment(*statuses), k) == expected


def test_assessment_is_invariant_across_thresholds() -> None:
    """The property the unified officer lacks.

    Under the unified officer, moving the rule from 1-of-3 to 2-of-3 moved the
    criteria-met count up on 37 of 39 briefings. Here the statuses are computed
    once, so re-scoring cannot touch them.
    """
    a = assessment("met", "not_met", "met")
    before = [dict(e) for e in a]
    decisions = {k: decide(a, k) for k in (1, 2, 3)}
    assert a == before, "decide() mutated the assessment"
    assert count_met(a) == 2
    assert decisions == {1: NOTIFY, 2: NOTIFY, 3: ROUTINE}


@pytest.mark.parametrize("k", [0, -1, 4, 99])
def test_threshold_outside_the_assessment_is_an_error(k: int) -> None:
    with pytest.raises(ValueError, match="outside 1..3"):
        decide(assessment("met", "met", "met"), k)


def test_empty_assessment_refuses_rather_than_defaulting() -> None:
    """A missing assessment must not silently become a routine update."""
    with pytest.raises(ValueError, match="empty assessment"):
        decide([], 1)


@pytest.mark.parametrize("bad", ["yes", "true", "partial", "", "MET?"])
def test_unknown_status_raises(bad: str) -> None:
    with pytest.raises(ValueError, match="unknown criterion status"):
        count_met(assessment("met", bad, "not_met"))


def test_unknown_status_raises_through_decide() -> None:
    with pytest.raises(ValueError, match="unknown criterion status"):
        decide(assessment("met", "partially met", "met"), 1)


def test_decisions_match_the_canonical_strings() -> None:
    """A drift here would silently unpool this arm from every stored result."""
    from sedition.agents.decisions import CANONICAL_DECISIONS

    assert NOTIFY in CANONICAL_DECISIONS
    assert ROUTINE in CANONICAL_DECISIONS
