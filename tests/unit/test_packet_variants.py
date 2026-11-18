"""Packet variants and the dataset's block permutation.

The dataset permutes the threat packet's twelve ids; a subset packet has
eleven. Without restriction `_reports_in_order` raises on every benign-arm
episode (found on the first mock run of the two-axis launcher, 2026-08-23).

The subset/benign arm is closed in this release: both tables are empty and
`resolve_packet` refuses a subset variant with a clear reason. Explicit
closure assertions keep that behavior visible.
"""
from __future__ import annotations

import pytest

from sedition.packets.variants import SUBSET_TABLE, resolve_packet, variant_permutation
from sedition_inspect.dataset import make_permutation


# These tests inspect twin STRUCTURE -- report ids, permutations, status text --
# which is review work, not a scored run. The DRAFT gate (PREREGISTRATION 73.1)
# correctly refuses draft twins to runs; this is the sanctioned bypass, the same
# one scripts/build_twin_criterion_table.py uses.
@pytest.fixture(autouse=True)
def _allow_draft_twins(monkeypatch):
    from sedition.packets import variants
    monkeypatch.setattr(variants, "ALLOW_DRAFT_TWINS", True)
    variants.control_packet.cache_clear()
    yield
    variants.control_packet.cache_clear()



#: The live MS packets. Used where the old tests parametrized over
#: `sorted(SUBSET_TABLE)`, which is now EMPTY -- and a parametrize over an
#: emptied table collects ZERO cases and reports as a skip, which is how a
#: guard stops guarding without anything turning red.
MS_PACKETS = ("E01-MS", "E02-MS", "E03-MS")


def test_the_subset_arm_is_closed_and_says_so() -> None:
    """The closure is an executed assertion, not the absence of a test.

    Reopening the arm requires independently deriving and validating report
    drops for every released packet; it must not be inferred from report
    numbers alone.
    """
    from sedition.packets.variants import CONTROL_SUBSET_TABLE

    assert SUBSET_TABLE == {}
    assert CONTROL_SUBSET_TABLE == {}


@pytest.mark.parametrize("packet_id", MS_PACKETS)
@pytest.mark.parametrize("variant", ["subset_benign", "subset_matched",
                                     "control_subset_resolution",
                                     "control_subset_inert"])
def test_asking_for_a_subset_variant_raises_with_the_closure_reason(
    packet_id: str, variant: str,
) -> None:
    """A run that asks for a closed arm must be told WHY, not get a KeyError.

    This replaces the old parametrize over `sorted(SUBSET_TABLE)`, which now
    collects nothing. The subject moved from "the arm behaves correctly" to
    "the arm refuses correctly", so the absence of the arm is itself tested.
    """
    with pytest.raises(ValueError, match="CLOSED"):
        resolve_packet(packet_id, variant)


def test_threat_and_twin_permutations_are_unchanged() -> None:
    """Closing the subset arm must not have disturbed the two live variants."""
    for packet_id in MS_PACKETS:
        threat = resolve_packet(packet_id, "threat")
        event_id, version = packet_id.split("-", 1)
        block = make_permutation(threat.report_ids, 20260814, event_id, version, 901)
        assert variant_permutation(threat, block) == block
        assert variant_permutation(resolve_packet(packet_id, "control"), block) == block


def test_permutation_missing_a_kept_report_raises() -> None:
    """`variant_permutation` still refuses a permutation short a kept report.

    Built from a twin rather than from a subset packet, because subset
    packets can no longer be constructed. The guard is about the permutation
    check, not about which variant produced the packet.
    """
    pk = resolve_packet("E03-MS", "control")
    with pytest.raises(ValueError):
        variant_permutation(pk, tuple(pk.report_ids[:-1]))


def test_a_legacy_ablated_record_round_trips_to_control() -> None:
    """A record written in the legacy vocabulary loads and DISPLAYS as control.

    Stored identifiers are immutable: 882 committed episodes and every .eval
    say packet_variant "ablated" and carry ids ending "-ablated", forever.
    `canonical_variant` is the single seam that maps them forward, and it
    never mutates the stored value -- the raw record keeps its spelling while
    everything derived from it (resolution, display, new ids) comes out
    "control".
    """
    from sedition.enums import Cell
    from sedition.packets.variants import canonical_variant
    from sedition_inspect.dataset import build_sample
    from sedition_inspect.run_integrity import canonical_episode_id

    record = {"packet_variant": "ablated",
              "episode_id": "E01-MS-b5001-basic_straight-ablated"}

    # Display path: the external strings canonicalize...
    assert canonical_variant(record["packet_variant"]) == "control"
    assert canonical_episode_id(record["episode_id"]) == (
        "E01-MS-b5001-basic_straight-control")
    # ...while the stored raw values are preserved untouched.
    assert record["packet_variant"] == "ablated"
    assert record["episode_id"].endswith("-ablated")

    # A threat id (no variant suffix) must map to itself.
    assert canonical_episode_id("E01-SS-b00-basic_straight") == (
        "E01-SS-b00-basic_straight")

    # Load path: a request in the legacy vocabulary builds the sample the
    # current vocabulary builds, displayed under the current name.
    legacy = build_sample(packet_id="E01-MS", packet_variant="ablated",
                          cell=Cell.HONEST_STRAIGHT, block_index=0)
    current = build_sample(packet_id="E01-MS", packet_variant="control",
                           cell=Cell.HONEST_STRAIGHT, block_index=0)
    assert legacy.id == current.id
    assert legacy.id.endswith("-control")
    assert legacy.metadata["packet_variant"] == "control"
