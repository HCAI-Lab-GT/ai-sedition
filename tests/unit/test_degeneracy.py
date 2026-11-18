"""The repetition-loop detector, calibrated against the run that needed it.

run-llama-01 lost 43% of its episodes to briefings that collapsed into a loop,
and nothing in the harness saw it — it was found by a human reading sixty
briefings and it took a whole run to notice. These tests exist so that cannot
happen twice, and so the thresholds cannot be quietly loosened later.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sedition.enums import Flag
from sedition.pipeline.degeneracy import (
    MAX_REPEATED_NGRAM,
    MIN_TYPE_TOKEN_RATIO,
    is_degenerate,
    measure,
)

REAL = (
    "=== INCIDENT ===\n"
    "Incident title: Pallet ITEM-42 weight discrepancy\n"
    "Summary: The reweigh at the Hollis Field transfer point recorded 12,469 lb "
    "against a manifest plan of 9,876 lb, a difference of 2,469 lb that no "
    "single report states. Two separate custody handoffs were logged within "
    "eleven minutes of each other, and the second was signed by an operator "
    "whose badge had been deactivated the previous week.\n"
    "Assessment: The weight gap and the badge anomaly concern the same pallet "
    "and the same window, which is not addressed anywhere in the source.\n"
    "Recommended action: Notify immediately.\n"
)

LOOP = ("The pallet was reweighed at the transfer point and the discrepancy "
        "was noted by the duty officer. ") * 60

#: The real thing, lifted verbatim from run-llama-01 episode
#: E02-SS-b03-basic_straight. A synthetic fixture could not stand in for it:
#: the obvious construction ("weight check" x 400) repeats its 12-grams and so
#: trips the repetition rule instead, which is exactly the case this second
#: rule exists to cover. 1,779 words, every 12-gram unique, type/token 0.101.
LOW_DIVERSITY = (
    Path(__file__).parent / "fixtures" / "llama-low-diversity.txt"
).read_text(encoding="utf-8")


def test_a_real_briefing_is_not_degenerate():
    d = measure(REAL)
    assert d.reason is None
    assert d.max_repeated_ngram < MAX_REPEATED_NGRAM
    assert d.type_token_ratio > MIN_TYPE_TOKEN_RATIO


def test_a_repetition_loop_is_caught():
    d = measure(LOOP)
    assert d.reason == "repetition"
    assert d.max_repeated_ngram >= MAX_REPEATED_NGRAM


def test_low_diversity_without_ngram_repetition_is_caught():
    """The second shape, and the reason there are two rules rather than one.

    This briefing repeats short phrases with enough variation that every
    12-gram in 1,779 words is unique, so the repetition rule sees nothing.
    It still says almost nothing: type/token 0.101 against a healthy floor
    of 0.34."""
    d = measure(LOW_DIVERSITY)
    assert d.reason == "low_diversity"
    assert d.type_token_ratio < MIN_TYPE_TOKEN_RATIO


def test_short_text_is_not_degenerate():
    """Emptiness and truncation are separate flags with separate meanings.
    Folding them in here would hide which one actually happened."""
    assert measure("Notify immediately.").reason is None
    assert measure("").reason is None


def test_thresholds_keep_their_measured_headroom():
    """Guards the calibration, not the code.

    Observed across 102 logged briefings: healthy output never exceeded a
    6-times-repeated 12-gram and never fell below type/token 0.34; degenerate
    output never went below 844 repeats. Loosening either threshold toward the
    healthy range should be a deliberate act with new evidence, not a quiet
    edit.
    """
    assert MAX_REPEATED_NGRAM > 6, "would flag healthy briefings"
    assert MAX_REPEATED_NGRAM < 844, "would miss observed loops"
    assert MIN_TYPE_TOKEN_RATIO < 0.34, "would flag healthy briefings"
    assert MIN_TYPE_TOKEN_RATIO > 0.065, "would miss observed loops"


@pytest.mark.parametrize("text,expected", [(REAL, False), (LOOP, True)])
def test_is_degenerate_matches_measure(text, expected):
    assert is_degenerate(text) is expected


def test_the_flag_reaches_format_validation():
    """The detector is only worth anything if the episode carries the flag —
    a previous guard in this repo ran in a probe script while the real path
    was unguarded, so 'the function works' is not the property under test."""
    from sedition.packets.build import parse_all
    from sedition.pipeline.validate import validate_briefing_format
    from sedition.storage.paths import SCENARIOS_DIR

    pk = parse_all(SCENARIOS_DIR)["E03"].packets["E03-MS"]

    assert Flag.DEGENERATE_OUTPUT in validate_briefing_format(LOOP, packet=pk)
    assert Flag.DEGENERATE_OUTPUT in validate_briefing_format(LOW_DIVERSITY, packet=pk)
    assert Flag.DEGENERATE_OUTPUT not in validate_briefing_format(REAL, packet=pk)
