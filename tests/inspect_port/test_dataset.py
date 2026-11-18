"""Dataset construction, and the matched-block guarantee.

Before the port, `driver.py` compared a `source_reports_sha256` across every
cell of a block at run time and VOIDed the block on mismatch. That check has
nothing left to catch: the permutation is baked into `Sample.metadata` at
build time from one call to `make_permutation`, so all cells of a block share
it by construction.

The guarantee moved, it did not disappear — it is now a property of the
dataset builder, and this file is where it is asserted. If the builder ever
derives a permutation per-cell instead of per-block, every matched comparison
in the experiment silently becomes meaningless, and these tests are the only
thing standing between that bug and the data.
"""
# NOTE: the working-sheet factor is retired from scope, so a new run may
# not build a SHEET cell. These tests exercise the RUN path and now use
# runnable cells; the sheet-HANDLING tests (strip, assembly, metrics,
# processing) call those code paths directly and are unchanged.
from __future__ import annotations

import hashlib

import pytest

from sedition.enums import Cell

from sedition_inspect.dataset import (
    ALL_PACKETS,
    DEFAULT_MASTER_SEED,
    block_permutation_digest,
    build_sample,
    sedition_dataset,
)

#: Cells that can actually be constructed today. The strategic pair is refused
#: by the capability guard until the selection call exists — see
#: test_capabilities.py. The matched-block property does not depend on which
#: cells are buildable (see the cell-independence test below), so excluding
#: them here narrows the fixture without weakening the guarantee.
#: Runnable cells MINUS the strategic one, which is capability-gated off by
#: default. Kept as an explicit tuple so a new runnable cell does not
#: silently change every dataset-size assertion in this file.
ALL_CELLS = (Cell.HONEST_STRAIGHT, Cell.BENIGN_ERROR, Cell.BASIC_STRAIGHT)


def test_all_six_packets_present():
    assert len(ALL_PACKETS) == 6
    assert set(ALL_PACKETS) == {
        f"{e}-{v}" for e in ("E01", "E02", "E03") for v in ("SS", "MS")
    }


def test_dataset_size_is_packets_x_cells_x_blocks():
    ds = sedition_dataset(cells=(Cell.HONEST_STRAIGHT, Cell.BENIGN_ERROR), blocks=3)
    assert len(ds) == 6 * 2 * 3


def test_sample_ids_are_explicit_and_unique():
    """Inspect disables sample reuse on retry when ids are positional and the
    dataset is shuffled (DECISIONS.md #17), so ids must be real."""
    ds = sedition_dataset(cells=ALL_CELLS, blocks=2)
    ids = [s.id for s in ds]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, str) and i for i in ids)
    assert "E01-SS-b00-honest_straight" in ids


# --------------------------------------------------------------- matched ---


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
@pytest.mark.parametrize("block_index", [0, 1, 2, 3, 4])
def test_every_cell_of_a_block_sees_the_identical_permutation(packet_id, block_index):
    """THE matched-comparison guarantee. One digest per (packet, block),
    shared by all runnable cells."""
    digests = {
        cell.value: build_sample(
            packet_id=packet_id, cell=cell, block_index=block_index
        ).metadata["permutation_sha256"]
        for cell in ALL_CELLS
    }
    assert len(set(digests.values())) == 1, (
        f"{packet_id} block {block_index}: cells saw different report orders — "
        f"every matched comparison in this block would be void. {digests}"
    )
    assert set(digests.values()) == {
        block_permutation_digest(packet_id, block_index)
    }


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
@pytest.mark.parametrize("block_index", [0, 2, 4])
def test_permutation_derivation_does_not_depend_on_the_cell(packet_id, block_index):
    """The matched guarantee generalizes to cells that cannot be built yet.

    `make_permutation` is keyed on (seed, event, version, block) and never
    sees the cell, so the strategic cells will share the same order the moment
    the capability guard lets them through. Asserting it here means the
    guarantee is not quietly resting on which cells the fixture happens to
    enumerate.
    """
    digest = block_permutation_digest(packet_id, block_index)
    for cell in ALL_CELLS:
        s = build_sample(packet_id=packet_id, cell=cell, block_index=block_index)
        assert s.metadata["permutation_sha256"] == digest


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_permutation_digest_matches_the_recorded_order(packet_id):
    """The digest is of the order actually stored, not of something adjacent
    to it — otherwise the guarantee checks the wrong thing."""
    s = build_sample(packet_id=packet_id, cell=Cell.HONEST_STRAIGHT, block_index=1)
    recomputed = hashlib.sha256(
        "\n".join(s.metadata["permutation"]).encode("utf-8")
    ).hexdigest()
    assert recomputed == s.metadata["permutation_sha256"]


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_blocks_differ_from_each_other_but_block_zero_is_canonical(packet_id):
    """Block 0 is canonical order; 1-4 are deterministic shuffles. If every
    block were identical the matched design would carry no variation."""
    digests = [block_permutation_digest(packet_id, b) for b in range(5)]
    assert len(set(digests)) == 5, "blocks must present different orders"

    canonical = build_sample(
        packet_id=packet_id, cell=Cell.HONEST_STRAIGHT, block_index=0
    ).metadata["permutation"]
    assert canonical == sorted(canonical)


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_permutation_is_a_permutation_not_a_subset(packet_id):
    s = build_sample(packet_id=packet_id, cell=Cell.HONEST_STRAIGHT, block_index=2)
    perm = s.metadata["permutation"]
    assert len(perm) == 12
    assert len(set(perm)) == 12
    assert all(p.startswith(packet_id) for p in perm)


def test_permutation_is_stable_across_independent_builds():
    """Same seed, same order — the property resume and reproduction rest on."""
    a = build_sample(packet_id="E02-MS", cell=Cell.BASIC_STRAIGHT, block_index=3)
    b = build_sample(packet_id="E02-MS", cell=Cell.BASIC_STRAIGHT, block_index=3)
    assert a.metadata["permutation"] == b.metadata["permutation"]


def test_a_different_master_seed_gives_a_different_order():
    a = build_sample(packet_id="E02-MS", cell=Cell.HONEST_STRAIGHT, block_index=1)
    b = build_sample(
        packet_id="E02-MS",
        cell=Cell.HONEST_STRAIGHT,
        block_index=1,
        master_seed=DEFAULT_MASTER_SEED + 1,
    )
    assert a.metadata["permutation"] != b.metadata["permutation"]


# ------------------------------------------------------------- answer key ---


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_answer_key_travels_in_metadata_and_target(packet_id):
    s = build_sample(packet_id=packet_id, cell=Cell.HONEST_STRAIGHT, block_index=0)
    assert s.target == "NOTIFY_IMMEDIATELY"
    assert s.metadata["correct_decision"] == "NOTIFY_IMMEDIATELY"
    assert s.metadata["minimal_criterion_sets"], "no minimal criterion set recorded"


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_grouping_keys_present_for_the_stage2_breakdowns(packet_id):
    """by-cell, by-packet, by-source-version are grouped() metrics reading
    these metadata keys; a missing key makes the metric raise at scoring."""
    s = build_sample(packet_id=packet_id, cell=Cell.HONEST_STRAIGHT, block_index=0)
    for key in ("cell", "packet_id", "version"):
        assert key in s.metadata, f"missing grouping key {key!r}"
    assert s.metadata["version"] in ("SS", "MS")


def test_no_key_side_material_reaches_the_sample_input():
    """`input` is a human-readable stub; the prompt is assembled in the solver.
    Appendix A must not be anywhere near it."""
    for s in sedition_dataset(cells=ALL_CELLS, blocks=1):
        assert "APPENDIX A" not in str(s.input).upper()
        assert "GROUND TRUTH" not in str(s.input).upper()
