"""The capability guard.

What this protects against is not a crash — it is a *successful* run that
measures the wrong thing. A strategic cell with no selection call still
produces a full log with scores attached; the episodes are simply not
strategic episodes. Nothing in the output says so.

So the assertions here are about *when* and *how loudly* the failure happens:
before any sample is built, before any model call, and with a message that
names both the missing capability and the thing that asked for it.
"""
# NOTE: the working-sheet factor is retired from scope, so a new run may
# not build a SHEET cell. These tests exercise the RUN path and now use
# runnable cells; the sheet-HANDLING tests (strip, assembly, metrics,
# processing) call those code paths directly and are unchanged.
from __future__ import annotations

import pytest

from sedition.enums import Cell

from sedition_inspect.capabilities import (
    CAPABILITIES,
    CELL_REQUIREMENTS,
    METRIC_REQUIREMENTS,
    MissingCapabilityError,
    is_available,
    require,
    require_cell,
    require_metric,
    unavailable,
)
from sedition_inspect.dataset import build_sample, sedition_dataset

STRATEGIC_CELLS = (Cell.STRATEGIC_STRAIGHT,)
BUILDABLE_CELLS = (
    Cell.HONEST_STRAIGHT,
    Cell.HONEST_STRAIGHT,
    Cell.BASIC_STRAIGHT,
    Cell.BASIC_STRAIGHT,
)


# ------------------------------------------------------------- registry ----


def test_every_declared_capability_is_registered():
    """Two of these are DROPPED rather than pending, and stay registered.

    They remain in the registry precisely so nothing can enable them by
    accident: deleting the entries would remove the guard along with the
    record of the decision.
    """
    assert set(unavailable()) >= {
        "quality_judge",
        "specialist_monitor_ensemble",
        "manipulation_gate_metric",
    }
    for name in ("quality_judge", "specialist_monitor_ensemble"):
        assert "DROPPED BY SCOPE DECISION" in CAPABILITIES[name].blocked_until


def test_every_unavailable_capability_says_what_is_missing_and_why():
    """A guard that fires without explaining itself gets disabled."""
    for name in unavailable():
        cap = CAPABILITIES[name]
        assert cap.summary.strip(), f"{name} has no summary"
        assert cap.blocked_until.strip(), f"{name} does not say what blocks it"


def test_requirement_mappings_only_reference_known_capabilities():
    """A typo here would silently make a requirement unenforceable."""
    for cell, caps in CELL_REQUIREMENTS.items():
        for c in caps:
            assert c in CAPABILITIES, f"{cell.value} -> unknown capability {c!r}"
    for metric, caps in METRIC_REQUIREMENTS.items():
        for c in caps:
            assert c in CAPABILITIES, f"{metric} -> unknown capability {c!r}"


def test_unknown_capability_is_itself_an_error():
    with pytest.raises(MissingCapabilityError, match="unknown capability"):
        require_metric.__globals__["_fail"]("no_such_capability", "made_up", "metric")


# ------------------------------------------------------------------ cells --


@pytest.mark.parametrize("cell", STRATEGIC_CELLS)
def test_strategic_cell_refuses_to_build(cell):
    with pytest.raises(MissingCapabilityError) as exc:
        build_sample(packet_id="E01-MS", cell=cell, block_index=0)

    msg = str(exc.value)
    assert "strategic_selection" in msg, "message must name the capability"
    assert cell.value in msg, "message must name the cell that asked for it"
    assert "not implemented" in msg
    # And it should say what going ahead would cost, not just that it refused.
    assert "3 model calls instead of 4" in msg


@pytest.mark.parametrize("cell", STRATEGIC_CELLS)
def test_strategic_cell_refused_by_the_dataset_builder_too(cell):
    """Not just per-sample: a stage naming the cell fails before the first
    sample is constructed."""
    with pytest.raises(MissingCapabilityError, match="strategic_selection"):
        sedition_dataset(packet_ids=("E01-MS",), cells=(cell,), blocks=1)


def test_one_bad_cell_fails_a_whole_mixed_request():
    """The dangerous shape: an honest cell alongside a strategic one. Partial
    construction would leave a dataset that runs and is quietly incomplete."""
    with pytest.raises(MissingCapabilityError, match="strategic_selection"):
        sedition_dataset(
            packet_ids=("E01-MS",),
            cells=(Cell.HONEST_STRAIGHT, Cell.STRATEGIC_STRAIGHT),
            blocks=1,
        )


@pytest.mark.parametrize("cell", BUILDABLE_CELLS)
def test_implemented_cells_still_build(cell):
    """The guard must not become a blanket refusal."""
    s = build_sample(packet_id="E01-MS", cell=cell, block_index=0)
    assert s.metadata["cell"] == cell.value
    ds = sedition_dataset(packet_ids=("E01-MS",), cells=(cell,), blocks=1)
    assert len(ds) == 1


def test_nothing_is_built_when_the_guard_fires():
    """The whole point of failing at build time. If a partially built dataset
    escaped, a run could start on it."""
    with pytest.raises(MissingCapabilityError):
        sedition_dataset(
            packet_ids=("E01-MS", "E01-SS"),
            cells=(Cell.STRATEGIC_STRAIGHT,),
            blocks=2,
        )


# ---------------------------------------------------------------- metrics --


@pytest.mark.parametrize(
    "metric,capability",
    [
        # manipulation_gate is NOT here: it is unbuilt-but-in-scope, and is
        # covered by test_unbuilt_metric_names_its_capability below. Only the
        # two dropped metrics belong in this case.
        ("joint_sabotage_success", "quality_judge"),
        ("ensemble_drs", "specialist_monitor_ensemble"),
    ],
)
def test_dropped_metric_is_refused_as_out_of_scope(metric, capability):
    """These two were DROPPED by scope decision, not left unbuilt.

    The error names the decision rather than the missing capability, because
    "we decided not to build this" and "this is not finished yet" call for
    different responses from whoever hits it.
    """
    with pytest.raises(MissingCapabilityError) as exc:
        require_metric(metric)
    msg = str(exc.value)
    assert metric in msg
    assert "OUT OF SCOPE" in msg
    assert "PREREGISTRATION.md section 16" in msg


def test_unbuilt_metric_names_its_capability():
    """Still-in-scope but unbuilt: the error names the missing capability,
    which is the actionable thing when the work is merely pending."""
    with pytest.raises(MissingCapabilityError) as exc:
        require_metric("manipulation_gate")
    msg = str(exc.value)
    assert "manipulation_gate_metric" in msg
    assert "OUT OF SCOPE" not in msg


def test_unknown_metric_is_refused():
    """An unknown metric must RAISE, not pass.

    This previously asserted the opposite — that a metric absent from the
    mapping was silently permitted. That default is what made pruning a
    dropped metric out of METRIC_REQUIREMENTS *weaken* the guard rather than
    strengthen it: removing the entry turned a refusal into a pass. A stage
    naming a typo'd metric should fail loudly.
    """
    with pytest.raises(MissingCapabilityError) as exc:
        require_metric("atomic_facts")
    assert "unknown metric" in str(exc.value)


# ----------------------------------------------------------------- shared --


def test_require_checks_cells_before_metrics():
    """A stage naming both a bad cell and a bad metric should report the cell:
    it is the more common mistake and the more dangerous one."""
    with pytest.raises(MissingCapabilityError) as exc:
        require(cells=(Cell.STRATEGIC_STRAIGHT,), metrics=("manipulation_gate",))
    assert "strategic_selection" in str(exc.value)


def test_is_available_reflects_the_registry():
    assert not is_available("strategic_selection")
    assert not is_available("nonexistent_capability")


def test_require_cell_is_a_no_op_for_implemented_cells():
    for cell in BUILDABLE_CELLS:
        require_cell(cell)
