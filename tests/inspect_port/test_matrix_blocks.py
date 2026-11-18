"""Addressing blocks individually, which is what lets the matrix be halted.

`eval_set` keys resume on task identity. Re-invoking a cell with a different
`blocks` count is a DIFFERENT task and it refuses the log directory outright
rather than resuming — verified against a live mock run, which failed with
"Existing log file ... is not associated with a task passed to eval_set".

So "run one block, check the stopping rules, then run the rest into the same
directory" is not available. One eval_set call per block is, and that needs
blocks 1..4 to be addressable rather than only the first N.

The property these tests protect: making a block addressable changed nothing
about what that block IS.
"""
# NOTE: the working-sheet factor is retired from scope, so a new run may
# not build a SHEET cell. These tests exercise the RUN path and now use
# runnable cells; the sheet-HANDLING tests (strip, assembly, metrics,
# processing) call those code paths directly and are unchanged.
from __future__ import annotations

import dataclasses

import pytest

from sedition.enums import RETIRED_CELLS, RUNNABLE_CELLS, Cell

from sedition_inspect.capabilities import (
    CAPABILITIES,
    MissingCapabilityError,
)
from sedition_inspect.dataset import (
    block_permutation_digest,
    sedition_dataset,
)
from sedition_inspect.run import MATRIX_CELLS, run_matrix


def ids(ds):
    return [s.id for s in ds.samples]


def test_block_indices_selects_exactly_that_block():
    ds = sedition_dataset(
        packet_ids=("E01-SS", "E02-SS"),
        cells=(Cell.HONEST_STRAIGHT,),
        block_indices=(3,),
    )
    assert ids(ds) == [
        "E01-SS-b03-honest_straight",
        "E02-SS-b03-honest_straight",
    ]


def test_an_addressed_block_is_identical_to_the_one_blocks_n_would_build():
    """The whole safety argument. If block 3 built via block_indices differed
    in any way from block 3 built via blocks=4, every matched comparison
    involving it would be quietly broken."""
    whole = sedition_dataset(
        packet_ids=("E01-SS", "E03-MS"),
        cells=(Cell.HONEST_STRAIGHT, Cell.BASIC_STRAIGHT),
        blocks=4,
    )
    piece = sedition_dataset(
        packet_ids=("E01-SS", "E03-MS"),
        cells=(Cell.HONEST_STRAIGHT, Cell.BASIC_STRAIGHT),
        block_indices=(3,),
    )
    from_whole = {s.id: s for s in whole.samples if s.metadata["block_index"] == 3}
    assert set(from_whole) == set(ids(piece))

    for s in piece.samples:
        other = from_whole[s.id]
        assert s.metadata["permutation"] == other.metadata["permutation"]
        assert s.metadata["permutation_sha256"] == other.metadata["permutation_sha256"]
        assert s.target == other.target
        assert s.metadata["master_seed"] == other.metadata["master_seed"]


def test_matched_ness_survives_per_block_execution():
    """Every cell of a block must still see byte-identical reports in
    identical order — the guarantee the whole design rests on — when those
    cells are run one eval_set call at a time."""
    for b in range(5):
        digests = set()
        for cell in (Cell.HONEST_STRAIGHT, Cell.BASIC_STRAIGHT, Cell.BENIGN_ERROR):
            ds = sedition_dataset(
                packet_ids=("E03-MS",), cells=(cell,), block_indices=(b,)
            )
            digests.add(ds.samples[0].metadata["permutation_sha256"])
        assert len(digests) == 1, f"block {b} is not matched across cells"
        assert digests.pop() == block_permutation_digest("E03-MS", b)


def test_default_behaviour_is_unchanged():
    """Every existing call site passes `blocks` and no `block_indices`."""
    a = sedition_dataset(packet_ids=("E01-SS",), blocks=3)
    b = sedition_dataset(packet_ids=("E01-SS",), blocks=3, block_indices=None)
    assert ids(a) == ids(b) == [
        "E01-SS-b00-honest_straight",
        "E01-SS-b01-honest_straight",
        "E01-SS-b02-honest_straight",
    ]


def test_the_matrix_covers_every_runnable_cell_exactly_once():
    """SHEET is retired, so the matrix is the four analyst conditions. The
    retired cells stay in the enum for stored-episode readability and must NOT
    appear here."""
    # benign_error retired 2026-08-27 (subset mechanism closed 2026-08-26).
    assert len(MATRIX_CELLS) == 4   # incl. degraded_straight, the fatigue capability control
    assert len(set(MATRIX_CELLS)) == 4
    assert {Cell(c) for c in MATRIX_CELLS} == set(RUNNABLE_CELLS)
    assert not {Cell(c) for c in MATRIX_CELLS} & set(RETIRED_CELLS)


def test_honest_cells_run_first():
    """If the environment is broken, the honest cells are where it shows up as
    something other than 'the sabotage worked'."""
    # The non-adversarial conditions run first. (benign_error sat here until
    # it was retired on 2026-08-27.)
    assert MATRIX_CELLS[0] == "honest_straight"
    assert MATRIX_CELLS[1] == "degraded_straight"
    assert MATRIX_CELLS[-1].startswith("strategic")


def test_the_matrix_refuses_an_unbuilt_cell_before_spending_anything(tmp_path):
    """The registry's promise is "refuse before spending", and the runner used
    to break it.

    `require_cell` fires at dataset-build time, which inside the cell loop is
    cell index 4 — after four cells have been paid for. With
    strategic_selection off that was ~120 episodes of spend before the error.
    The check now runs over every cell before the first eval_set call.
    """
    log_dir = tmp_path / "matrix"
    with pytest.raises(MissingCapabilityError) as exc:
        run_matrix(
            model_set="mock",
            packets=("E01-SS",),
            blocks=1,
            log_dir=str(log_dir),
        )
    assert "strategic" in str(exc.value)
    assert not log_dir.exists(), "refused, but only after creating a log dir"


def test_the_matrix_runs_strategic_cells_once_the_flag_is_on(tmp_path, monkeypatch):
    """The runner had never met a strategic cell.

    Flipping the flag for the real run would otherwise be the first time this
    path executed, on a paid provider, mid-matrix.
    """
    for name in ("strategic_selection",):
        monkeypatch.setitem(
            CAPABILITIES, name, dataclasses.replace(CAPABILITIES[name], available=True)
        )

    rc = run_matrix(
        model_set="mock",
        packets=("E01-SS",),
        cells=("strategic_straight",),
        blocks=1,
        log_dir=str(tmp_path / "matrix"),
    )
    assert rc == 0
