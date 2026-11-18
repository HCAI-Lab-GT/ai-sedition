"""Packets -> Inspect `Sample`s.

DECISIONS.md #16: the report permutation and the answer key are precomputed
into `Sample.metadata` at dataset-build time rather than derived at solve
time. Two consequences worth stating, because they replace runtime machinery
the pre-port harness had:

* **Matched blocks are guaranteed by construction.** Every cell of a block is
  built from one call to `make_permutation`, so all cells in a block see
  byte-identical reports by definition. `driver.py`'s `_assert_block_matched`
  VOID check has nothing left to catch; `test_dataset.py` asserts the property
  at build time instead.
* **Sample ids are explicit.** Inspect disables sample reuse on retry when
  ids are positional and the dataset is shuffled (#17), so every Sample
  carries the episode id the old harness used: `E01-SS-b00-honest_straight`.
"""
from __future__ import annotations

import hashlib

from sedition.enums import RUNNABLE_CELLS, Cell, Decision
from sedition.packets.variants import (
    CONTROL_DERIVED,
    CONTROL_SUBSET_TABLE,
    SUBSET_TABLE,
    canonical_variant,
)
from sedition.pipeline.blocks import make_permutation
from sedition.pipeline.episode import episode_id

from inspect_ai.dataset import MemoryDataset, Sample

from ._resources import answer_key, packet, target_slots
from .capabilities import require_cell

#: Identical across every stage, so blocks stay comparable when a later stage
#: appends cells to the same blocks.
DEFAULT_MASTER_SEED = 20260814

#: The full environment: 3 events x 2 source versions. SS and MS are the
#: manipulated variable and are never pooled.
ALL_PACKETS: tuple[str, ...] = (
    "E01-SS", "E01-MS",
    "E02-SS", "E02-MS",
    "E03-SS", "E03-MS",
)

def _refuse_if_subset_arm_closed(table, packet_id: str, packet_variant: str) -> None:
    """Raise with the reason rather than a bare KeyError from the table.

    `build_sample` reads the subset tables directly, so it needs its own
    refusal: `variants.subset_packet` never gets called on this path. Both
    tables are intentionally empty in the release. A bare table KeyError would
    look like a missing packet rather than a closed experimental arm.
    """
    if table:
        return
    raise ValueError(
        f"the subset/benign arm is CLOSED: cannot build a {packet_variant!r} "
        f"sample for {packet_id!r}. This release contains no reviewed "
        f"per-packet subset definition."
    )


def build_sample(
    *,
    packet_id: str,
    packet_variant: str = "threat",
    cell: Cell,
    block_index: int,
    master_seed: int = DEFAULT_MASTER_SEED,
    overlay: str = "current",
    report_order: list[str] | None = None,
) -> Sample:
    """One episode. `metadata` carries everything the solver and scorers need
    so that neither has to reach back into the scenario files at run time."""
    # Before anything else: refuse a cell whose implementation is missing.
    # This is the earliest point at which the request is known, and failing
    # here means no sample exists, no call is made, and no money is spent.
    require_cell(cell)

    # Legacy spellings ("ablated", "subset_control", ...) canonicalize here,
    # once, so the id, the metadata and the answer-key flip below all agree.
    # New episode ids therefore end "-control"; ids already committed keep
    # "-ablated" and stay parseable (sedition.packets.variants.canonical_variant).
    packet_variant = canonical_variant(packet_variant)

    event_id, version = packet_id.split("-", 1)
    pk = packet(packet_id)
    if report_order is None:
        permutation = make_permutation(pk.report_ids, master_seed, event_id, version, block_index)
    else:
        if sorted(report_order) != sorted(pk.report_ids):
            raise ValueError(f"Invalid report order for {packet_id} block {block_index}")
        permutation = tuple(report_order)

    key = answer_key().packets[packet_id]
    target = target_slots().get(packet_id)

    # The answer key describes the THREAT packet. A control twin (legacy
    # "ablated") resolves the
    # decisive elements rather than removing them, so its correct answer is
    # routine update -- `variants.py` says so in its own first paragraph, and it
    # is the entire point of the false-positive row. Taking the threat key
    # unconditionally scored the twins gate's 18 correct ROUTINE decisions as
    # 18 failures against a NOTIFY target; the reported 18/18 was read from
    # `wo_decision` and was right, but `officer_decision` in the same log said
    # 0/18. See PREREGISTRATION 52 and 67.
    #
    # Only the twin-derived variants flip. Report subsetting deliberately
    # does NOT: 42.2 holds
    # criteria A and C satisfiable under both the benign and the control drop,
    # "so the officer's correct answer is unchanged".
    correct_decision = key.correct_decision
    minimal_sets = [list(s) for s in key.minimal_criterion_satisfying_report_sets]
    if packet_variant in CONTROL_DERIVED:
        correct_decision = Decision.INCLUDE_IN_ROUTINE_UPDATE.value
        # Every criterion is defeated by a located authorisation, so no set of
        # reports satisfies one. Carrying the threat routes here would let
        # graded_outcome count surviving routes that cannot exist.
        minimal_sets = []

    # Which report the subset arms removed. Recorded as a first-class field
    # because on a TWIN the identity of the removed report decides what the
    # episode measures: remove the report carrying the resolution and the
    # officer is left with an unresolved anomaly and no closing record, which is
    # alarm injection rather than a benign-error control. Recovering that from
    # the variant name alone forces every reader to know the table.
    removed_report_id = ""
    if packet_variant in ("subset_benign", "subset_matched"):
        _refuse_if_subset_arm_closed(SUBSET_TABLE, packet_id, packet_variant)
        removed_report_id = SUBSET_TABLE[packet_id][
            "benign" if packet_variant == "subset_benign" else "control"]
    elif packet_variant in ("control_subset_resolution", "control_subset_inert"):
        _refuse_if_subset_arm_closed(CONTROL_SUBSET_TABLE, packet_id, packet_variant)
        removed_report_id = CONTROL_SUBSET_TABLE[packet_id][
            "resolution" if packet_variant.endswith("resolution") else "inert"]

    # GROUND TRUTH ON THE RESOLUTION-REMOVAL ARM IS CONTESTED, per packet, and
    # is deliberately NOT asserted here. On E01-MS the anomaly report is
    # byte-identical to its parent and still reads "Unresolved", so removing the
    # reschedule arguably restores NOTIFY. On E02-MS and E03-MS the anomaly is
    # resolved in its own report, so removing the reschedule only drops the
    # departure and ROUTINE stands. Rather than guess, these arms are analysed
    # by ESCALATION RATE and the resolution-vs-inert contrast, never by accuracy
    # against this target. See PREREGISTRATION 75.
    eid = episode_id(event_id, version, block_index, cell.value, packet_variant)

    return Sample(
        id=eid,
        # The analyst prompt is assembled in the solver from the packet and
        # permutation, so `input` carries only a human-readable stub. Putting
        # the real prompt here would mean Inspect seeds `state.messages` with
        # it, and the officer/monitor payloads are built separately anyway.
        input=f"{packet_id} · {cell.value} · block {block_index}",
        metadata={
            "episode_id": eid,
            "packet_id": packet_id,
            "packet_variant": packet_variant,
            "event_id": event_id,
            "version": version,
            "block_index": block_index,
            "master_seed": master_seed,
            "cell": cell.value,
            "overlay": overlay,
            "policy": cell.policy.value,
            "working_condition": cell.working_condition.value,
            "permutation": list(permutation),
            # Shared by every cell of this block. Equality across a block is
            # the matched-comparison guarantee, asserted at build time.
            "permutation_sha256": hashlib.sha256(
                "\n".join(permutation).encode("utf-8")
            ).hexdigest(),
            # --- answer key (scorer-side; never rendered into a prompt) ---
            "correct_decision": correct_decision,
            "removed_report_id": removed_report_id,
            "minimal_criterion_sets": minimal_sets,
            "target_report_ids": list(target.target_report_ids) if target else [],
        },
        # `Target` is the officer decision the packet should produce.
        target=correct_decision,
    )

def block_permutation_digest(
    packet_id: str, block_index: int, master_seed: int = DEFAULT_MASTER_SEED
) -> str:
    """SHA-256 of the report order a block presents.

    This is what makes matched-ness checkable. Every cell of a block is built
    from one call to `make_permutation`, so all cells share this digest by
    construction — `tests/inspect_port/test_dataset.py` asserts it at build
    time, which is where the old runtime `_assert_block_matched` VOID check
    used to live.
    """
    event_id, version = packet_id.split("-", 1)
    perm = make_permutation(
        packet(packet_id).report_ids, master_seed, event_id, version, block_index
    )
    return hashlib.sha256("\n".join(perm).encode("utf-8")).hexdigest()

def sedition_dataset(
    *,
    packet_ids: tuple[str, ...] = ALL_PACKETS,
    packet_variant: str = "threat",
    cells: tuple[Cell, ...] = (Cell.HONEST_STRAIGHT,),
    blocks: int = 1,
    block_indices: tuple[int, ...] | None = None,
    master_seed: int = DEFAULT_MASTER_SEED,
    overlay: str = "current",
    report_orders: dict[str, list[str]] | None = None,
    #: Escape hatch for tests that must exercise a RETIRED cell — chiefly the
    #: payload-privacy canary, which uses working-sheet text as its marker for
    #: private analyst material leaking into logged messages. Real runs leave
    #: this False so the retired factor cannot come back by accident.
) -> MemoryDataset:
    """Block-major, matching the pre-port driver's iteration order: every cell
    of a block is adjacent, so a truncated run leaves whole blocks.

    `block_indices` names the blocks explicitly instead of taking the first
    `blocks` of them. It exists because `eval_set` keys resume on task
    identity: re-invoking with a different `blocks` count is a DIFFERENT task
    and it refuses the log directory outright rather than resuming (verified,
    not assumed — it errors with "not associated with a task passed to
    eval_set"). Running one block per `eval_set` call is therefore the only
    way to checkpoint inside a cell, and that needs blocks 1..4 to be
    addressable, not just the first N.

    Block indices are unchanged by this: `block_indices=(3,)` builds exactly
    the sample `blocks=4` would have built for block 3, same id, same
    permutation. Nothing about matched-ness moves.
    """
    # Check every requested cell up front rather than discovering the problem
    # on the first sample that happens to use it.
    for cell in cells:
        require_cell(cell)
        
    indices = tuple(range(blocks)) if block_indices is None else tuple(block_indices)

    samples = [
        build_sample(
            packet_id=pid, packet_variant=packet_variant,
            cell=cell, block_index=b, master_seed=master_seed,
            overlay=overlay,
            report_order=None if report_orders is None else report_orders[f"{pid}:{b}"],
        )
        for b in indices
        for pid in packet_ids
        for cell in cells
    ]
    return MemoryDataset(samples=samples, name="sedition_briefing")
