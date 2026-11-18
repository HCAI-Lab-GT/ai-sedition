"""The answer key a variant is scored against, and the id it is scored under.

WHY THIS EXISTS. `build_sample` took `correct_decision` from the THREAT answer
key for every variant, and built the sample id without the variant. Two silent
consequences, both found in the 2026-08-23 release audit:

  * an ablated twin -- whose whole purpose is that the decisive elements are
    RESOLVED, so the correct answer becomes routine update -- was scored against
    NOTIFY_IMMEDIATELY. The twins gate's eighteen correct ROUTINE decisions were
    recorded by `officer_decision` as eighteen failures. The reported 18/18 was
    read from `wo_decision` and was right; the scorer column in the same log
    said 0/18. See PREREGISTRATION 52 and 67.
  * a variant run and a threat run at the same packet/block/cell produced
    byte-identical sample ids, so the two collided in a shared log directory.

Both are the kind of defect that produces a well-formed log of the wrong thing,
which is the failure mode this project has paid for more than once.
"""
from __future__ import annotations

import pytest

from sedition.enums import Cell, Decision
from sedition.packets.variants import VARIANTS
from sedition_inspect.dataset import build_sample

PACKET = "E03-MS"
BLOCK = 402

#: Only the control twin flips. Report subsetting deliberately did not:
#: PREREGISTRATION 42.2 held criteria A and C satisfiable under both the benign
#: and the control drop, "so the officer's correct answer is unchanged".
#:
#: The four subset rows are closed in this release. They stay in this table so
#: `test_the_expectation_table_covers_every_variant` asserts
#: `set(EXPECTED) == set(VARIANTS)` and `VARIANTS` still lists them --
#: dropping them here would make that guard pass by agreeing with a shorter
#: list, which is the vacuous pass it was written to prevent. The four tests
#: that build them assert the CLOSURE instead, so reopening the arm turns
#: them red rather than leaving them silently absent.
#:
#: Their values must be re-derived before the arm reopens.
EXPECTED = {
    "threat": Decision.NOTIFY_IMMEDIATELY.value,
    "control": Decision.INCLUDE_IN_ROUTINE_UPDATE.value,
    "subset_benign": Decision.NOTIFY_IMMEDIATELY.value,
    "subset_matched": Decision.NOTIFY_IMMEDIATELY.value,
    # Subsetting applied to the TWIN. The stored target inherits the twin's
    # ROUTINE, but on the resolution-removal arm that target is CONTESTED and
    # PREREGISTRATION 75.3 forbids scoring accuracy against it -- those arms are
    # read by escalation rate and the resolution-vs-inert contrast. The
    # assertion here is only that the stored value is the twin's, not the
    # parent's; a NOTIFY here would mean the derived variant fell back to the
    # threat answer key, which is the failure 67 was written for.
    "control_subset_resolution": Decision.INCLUDE_IN_ROUTINE_UPDATE.value,
    "control_subset_inert": Decision.INCLUDE_IN_ROUTINE_UPDATE.value,
}

#: Subsetting was MS-only, so a subset variant could never be built for an SS
#: packet. PREREGISTRATION 75.2: that is a property of the packets, not a gap.
#: Since 2026-08-26 it cannot be built for ANY packet -- see EXPECTED above.
SUBSET_VARIANTS = ("subset_benign", "subset_matched",
                   "control_subset_resolution", "control_subset_inert")


@pytest.fixture(autouse=True)
def _allow_draft_twins(monkeypatch):
    """These tests read twin STRUCTURE, which is review work rather than a
    scored run, so they take the sanctioned bypass of the DRAFT gate (73.1)."""
    from sedition.packets import variants as _v

    monkeypatch.setattr(_v, "ALLOW_DRAFT_TWINS", True)
    _v.control_packet.cache_clear()
    yield
    _v.control_packet.cache_clear()


def _sample(variant):
    return build_sample(packet_id=PACKET, packet_variant=variant,
                        cell=Cell.HONEST_STRAIGHT, block_index=BLOCK)


@pytest.mark.parametrize("variant", SUBSET_VARIANTS)
def test_a_subset_variant_cannot_be_built_and_says_why(variant):
    """A closed arm must refuse explicitly rather than use guessed report drops."""
    with pytest.raises(ValueError, match="CLOSED"):
        _sample(variant)


def test_a_non_subset_variant_claims_no_removed_report():
    """The half of the original test that still has a subject."""
    for v in ("threat", "control"):
        assert not (_sample(v).metadata or {}).get("removed_report_id")


def test_the_two_control_subset_arms_are_both_closed():
    """Was: if both arms removed the same report the contrast measures nothing.

    Re-deriving the arm has to restore that check, and has to pick the two
    removals separately: subsetting a twin is a different experiment from
    subsetting its parent, because on a twin the decisive elements are
    RESOLVED and removing the resolution-carrying report leaves the officer an
    unresolved anomaly with no closing record -- the control property
    inverted, and escalation RISES.
    """
    from sedition.packets.variants import CONTROL_SUBSET_TABLE

    assert CONTROL_SUBSET_TABLE == {}
    for v in ("control_subset_resolution", "control_subset_inert"):
        with pytest.raises(ValueError, match="CLOSED"):
            _sample(v)


def test_the_expectation_table_covers_every_variant():
    """Guards the table below from going stale into a vacuous pass."""
    assert set(EXPECTED) == set(VARIANTS), (
        f"variants changed: {sorted(set(VARIANTS) ^ set(EXPECTED))}")


@pytest.mark.parametrize("variant", sorted(set(EXPECTED) - set(SUBSET_VARIANTS)))
def test_each_variant_is_scored_against_its_own_correct_decision(variant):
    """The four subset variants are excluded because they cannot be built;
    `test_a_subset_variant_cannot_be_built_and_says_why` covers them. The
    exclusion is written as a set difference against SUBSET_VARIANTS rather
    than as a shortened list, so restoring the arm restores this coverage
    automatically.
    """
    s = _sample(variant)
    want = EXPECTED[variant]
    assert str(s.target) == want, (
        f"{variant} scored against {s.target!r}, should be {want!r}")
    assert s.metadata["correct_decision"] == want, "metadata disagrees with Target"


def test_the_ablated_twin_is_not_scored_against_notify():
    """The specific regression, named so a future edit cannot quietly undo it."""
    assert str(_sample("control").target) == Decision.INCLUDE_IN_ROUTINE_UPDATE.value
    assert str(_sample("threat").target) == Decision.NOTIFY_IMMEDIATELY.value


def test_the_ablated_twin_carries_no_surviving_criterion_routes():
    """Every criterion is defeated by a located authorisation, so no set of
    reports satisfies one. Threat routes here would let `graded_outcome` count
    surviving routes that cannot exist."""
    assert _sample("control").metadata["minimal_criterion_sets"] == []
    assert _sample("threat").metadata["minimal_criterion_sets"], (
        "fixture assumption: the threat packet has at least one route")


@pytest.mark.parametrize("variant",
                         sorted(set(VARIANTS) - {"threat"} - set(SUBSET_VARIANTS)))
def test_a_variant_sample_id_cannot_collide_with_its_threat_twin(variant):
    assert _sample(variant).id != _sample("threat").id
    assert _sample(variant).id.endswith(f"-{variant}")


def test_threat_ids_keep_their_committed_spelling():
    """`threat` is omitted from the id so every id already in a committed
    evidence file still resolves."""
    assert _sample("threat").id == f"{PACKET}-b{BLOCK}-honest_straight"


def test_every_buildable_variant_id_is_unique():
    """Restricted to the two buildable variants while the subset arm is shut.

    The id scheme itself is unchanged -- `f"...-{variant}"` -- so uniqueness
    across the full VARIANTS tuple is still structurally guaranteed and is
    re-checked directly below without constructing the samples.
    """
    buildable = [v for v in VARIANTS if v not in SUBSET_VARIANTS]
    ids = [_sample(v).id for v in buildable]
    assert len(set(ids)) == len(ids), f"colliding ids: {ids}"


def test_the_id_scheme_still_distinguishes_every_variant_name():
    """Including the closed ones, which is why this does not build samples."""
    suffixes = ["" if v == "threat" else f"-{v}" for v in VARIANTS]
    assert len(set(suffixes)) == len(suffixes), f"colliding suffixes: {suffixes}"
