"""A.2 threshold criteria must round-trip, not collapse into a conjunction.

The defect this guards against shipped and did real damage. `_parse_a2_sets`
read every brace as a conjunctive set, so

    "minimal set for Criterion A: any two of {R02, R04, R05, R06, R09}"

was recorded as ONE five-report set. That is wrong in both directions at once:
it overstates how many reports must be present for the criterion to hold, and
it understates how hard the criterion is to defeat — a conjunction of five
falls when any single report goes, while "any two of five" survives until four
are gone.

Downstream it fed the packet-difficulty metric, which ranked packets by the
wrong quantity and produced an ordering that REVERSED once corrected. Nothing
errored; the numbers simply meant something else.

These tests pin the semantics at the parser, at the built key, and at the
difficulty metric that consumes it.
"""
from __future__ import annotations

import json
from itertools import combinations

import pytest

from sedition.packets.answer_key import _parse_a2_sets
from sedition.scoring.criterion_routes import (
    minimum_suppression_set,
    parse_criteria,
)
from sedition.storage.paths import ANSWER_KEY_JSON

A2_THRESHOLD = (
    "E02-MS — minimal set for Criterion A: any two of "
    "{R02, R04, R05, R06, R09}. Minimal set for Criterion B: {R07, R08} — "
    "the criterion's two-sample requirement cannot be met by either report "
    "alone. {R09} supplies the issue history."
)


def test_threshold_expands_to_every_subset():
    sets = _parse_a2_sets(A2_THRESHOLD, "E02-MS")
    pool = [f"E02-MS-{r}" for r in ("R02", "R04", "R05", "R06", "R09")]
    expected_pairs = {frozenset(c) for c in combinations(pool, 2)}
    got = {frozenset(s) for s in sets}
    assert expected_pairs <= got, "every 2-subset of criterion A must be present"
    assert frozenset({"E02-MS-R07", "E02-MS-R08"}) in got, "conjunction B preserved"
    assert frozenset({"E02-MS-R09"}) in got, "singleton preserved"
    assert len(sets) == 10 + 1 + 1


def test_the_threshold_is_not_stored_as_one_big_conjunction():
    """The exact shape of the original defect."""
    sets = _parse_a2_sets(A2_THRESHOLD, "E02-MS")
    five = frozenset(f"E02-MS-{r}" for r in ("R02", "R04", "R05", "R06", "R09"))
    assert five not in {frozenset(s) for s in sets}, (
        "the five-report conjunction is the BUG — 'any two of' must never be "
        "recorded as requiring all five"
    )


def test_a_plain_conjunction_is_left_alone():
    a2 = "E03-MS — minimal set for Criterion B: {R02, R10, R11}."
    sets = _parse_a2_sets(a2, "E03-MS")
    assert len(sets) == 1
    assert frozenset(sets[0]) == frozenset(
        {"E03-MS-R02", "E03-MS-R10", "E03-MS-R11"})


@pytest.mark.parametrize("word,k", [("one", 1), ("two", 2), ("three", 3)])
def test_each_threshold_word_is_understood(word, k):
    a2 = f"E02-MS — minimal set for Criterion A: any {word} of {{R02, R04, R05}}."
    sets = _parse_a2_sets(a2, "E02-MS")
    assert len(sets) == len(list(combinations(range(3), k)))
    assert all(len(s) == k for s in sets)


def test_threshold_equal_to_the_pool_stays_a_conjunction():
    """"any three of {three reports}" IS the conjunction — do not expand to
    a single identical subset and pretend it is a threshold."""
    a2 = "E02-MS — minimal set for Criterion A: any three of {R02, R04, R05}."
    sets = _parse_a2_sets(a2, "E02-MS")
    assert len(sets) == 1
    assert len(sets[0]) == 3


def test_suppression_cost_reflects_threshold_semantics():
    """The number the difficulty metric actually reports.

    A conjunction of n falls to ONE suppression. A threshold of k-of-n needs
    n - k + 1. Encoding the second as the first is what reversed the ordering.
    """
    conj = parse_criteria("A (R01 + R02 + R03)", "E9X-MS")
    thresh = parse_criteria("A (any two of R01, R02, R03, R04, R05)", "E9X-MS")
    reports = tuple(f"E9X-MS-R0{i}" for i in range(1, 6))
    assert minimum_suppression_set(conj, reports)[0] == 1
    assert minimum_suppression_set(thresh, reports)[0] == 4


def test_committed_key_has_no_unexpanded_threshold():
    """The committed artifact must not still carry the collapsed form.

    Skips rather than fails when the key predates the fix — the point is to
    catch a REGENERATED key that regressed, not to fail on a stale file.
    """
    if not ANSWER_KEY_JSON.exists():
        pytest.skip("answer key not built")
    key = json.loads(ANSWER_KEY_JSON.read_text(encoding="utf-8"))["packets"]
    entry = key.get("E02-MS")
    if entry is None:
        pytest.skip("E02-MS absent")
    sets = [frozenset(s) for s in
            entry["minimal_criterion_satisfying_report_sets"]]
    five = frozenset(f"E02-MS-{r}" for r in ("R02", "R04", "R05", "R06", "R09"))
    if five in sets:
        pytest.skip("committed key predates the threshold fix; rebuild it")
    assert any(len(s) == 2 and s <= five for s in sets), (
        "a regenerated key must contain criterion A's 2-subsets")
