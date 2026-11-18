"""Anchors and scoring notes must never reach a model.

Anchors are the figures and identifiers the scorer keys on. They live in a
scorer-only field precisely because the fact descriptions ARE shown to the
monitor, and putting the values in a description would hand the monitor the
answer.

OPEN FINDING, SURFACED 2026-08-26: THE SHIPPED VOCABULARY LEAKS ITS ANCHORS.
See `ANCHOR_LEAK_FINDING` below. `test_no_anchor_value_reaches_the_monitor`
is strict-xfail against every packet until it is resolved.

A monitor told to look for 12,469 is not performing the task being measured.
It would score high on exactly the briefings that mention the figure and the
detection arm would be void — and the failure is silent, because the numbers
would look excellent.

The same applies to scoring notes, which are written as instructions to a
scorer ("Formed when the briefing states the difference...") and would tell a
monitor what a faithful briefing is supposed to contain.

This is the counterpart to test_payload_privacy.py: that file guards what the
ANALYST emits, this one guards what the VOCABULARY leaks.
"""
from __future__ import annotations

import pytest

from sedition.packets.fact_vocabulary import Fact, Review

from sedition_inspect._resources import vocabulary
from sedition_inspect.dataset import ALL_PACKETS

VOCAB = vocabulary()

#: Open limitation: 17 of the 23 released facts expose at least one scorer
#: anchor in the monitor-visible description (85 packet/fact/anchor triples
#: across the six packets). Rewriting descriptions or anchors would change the
#: instrument used for the released results, so the strict expected failures
#: keep the limitation visible.
ANCHOR_LEAK_FINDING = (
    "the shipped fact vocabulary states its anchors verbatim in the descriptions "
    "the monitor is shown; see ANCHOR_LEAK_FINDING in this file"
)


def _rendered_for(packet_id: str) -> str:
    """Exactly what a monitor prompt receives for this packet's vocabulary."""
    return VOCAB.render_for_monitor(packet_id)


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_no_scoring_note_text_reaches_the_monitor(packet_id):
    rendered = _rendered_for(packet_id)
    for fact in VOCAB.for_packet(packet_id):
        note = fact.scoring_note.strip()
        if not note:
            continue
        snippet = note[:40]
        assert snippet not in rendered, (
            f"{fact.fact_id}: scoring_note leaked into the monitor prompt"
        )


@pytest.mark.parametrize("packet_id", [
    pytest.param(p, marks=pytest.mark.xfail(strict=True,
                                            reason=ANCHOR_LEAK_FINDING))
    for p in ALL_PACKETS
])
def test_no_anchor_value_reaches_the_monitor(packet_id):
    """The strict expected failure documenting monitor-visible anchors."""
    rendered = _rendered_for(packet_id)
    for fact in VOCAB.for_packet(packet_id):
        for anchor in fact.anchors:
            assert anchor not in rendered, (
                f"{fact.fact_id}: anchor {anchor!r} leaked into the monitor "
                "prompt — a monitor told which figure to look for is not "
                "doing the task being measured"
            )


def test_the_guard_actually_catches_a_leak():
    """Proof the test above is not vacuous by construction.

    A monitor renderer that included anchors must fail this. Without this
    case, `test_no_anchor_value_reaches_the_monitor` would pass on an empty
    vocabulary forever and nobody would know it was asleep.

    IT WAS ASLEEP ANYWAY, for a reason this case could not catch: the guard
    was live and correct, and the packets it was pointed at had no anchors.
    A planted-leak test proves the detector works; it cannot prove the
    detector is aimed at anything. `test_the_shipped_vocabulary_has_anchors_
    to_leak` below is the missing half.
    """
    leaky = Fact(
        fact_id="X.leaky", fact_class="atomic", packets=("E03-MS",),
        constituents=(), carried_by=("E03-MS-R10",),
        description="A calibrated physical measurement of 12,469 lb.",
        scoring_note="", provenance={},
        review=Review(status="draft", reviewer=None, date=None),
        anchors=("12,469",),
    )
    # Simulating the renderer including the description, which is what it does.
    rendered = leaky.for_monitor().description
    assert any(a in rendered for a in leaky.anchors), (
        "the leak detector failed to detect a planted leak"
    )


def test_the_shipped_vocabulary_has_anchors_to_leak():
    """The half `test_the_guard_actually_catches_a_leak` could not supply.

    A leak detector aimed at facts with no anchors passes forever. This
    asserts the subject exists, so if the vocabulary is ever replaced by one
    with empty anchor fields, the xfail above will start XPASSing for the
    wrong reason and this fails first and says why.
    """
    anchored = [f.fact_id for pid in ALL_PACKETS
                for f in VOCAB.for_packet(pid) if f.anchors]
    assert anchored, (
        "no shipped fact carries an anchor, so the anchor-leak guard has no "
        "subject and passes vacuously -- exactly the state it was in before "
        "2026-08-26")


def test_monitor_facts_carry_no_scoring_note_field_at_all():
    """Structural, not textual: MonitorFact has no scoring_note attribute, so
    a renderer cannot leak what it was never handed."""
    fact = next(iter(VOCAB.for_packet("E03-MS")))
    monitor_view = fact.for_monitor()
    assert not hasattr(monitor_view, "scoring_note")
    assert not hasattr(monitor_view, "anchors")
    assert set(vars(monitor_view)) == {"fact_id", "description"}
