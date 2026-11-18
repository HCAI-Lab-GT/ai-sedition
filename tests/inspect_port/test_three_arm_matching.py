"""Within a matched block, all three analyst types see identical report order.

The milestone list requires this "by asserting order equality across arms in
a block, not by inspection" — so these tests compare the actual permutation
lists element by element, across every packet and block the pilot will use,
and then confirm the order a REAL rendered prompt presents is that same
permutation. A digest comparison alone would trust that the digest is honest;
the prompt comparison closes that loop.

Strategic cells are built with the capability guard satisfied test-locally.
The flag stays False on disk and in the registry after every test.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from sedition.enums import Cell

from sedition_inspect import capabilities
from sedition_inspect.dataset import ALL_PACKETS, sedition_dataset

THREE_ARMS = (Cell.HONEST_STRAIGHT, Cell.BASIC_STRAIGHT, Cell.STRATEGIC_STRAIGHT)
PILOT_BLOCKS = 5


@pytest.fixture
def strategic_enabled(monkeypatch):
    cap = capabilities.CAPABILITIES["strategic_selection"]
    monkeypatch.setitem(
        capabilities.CAPABILITIES,
        "strategic_selection",
        dataclasses.replace(cap, available=True),
    )
    yield
    assert capabilities.CAPABILITIES["strategic_selection"].available is True  # patched
    # monkeypatch restores the original after the test; the on-disk flag never moved.


def _samples_by_arm(packet_id: str, block: int):
    out = {}
    for cell in THREE_ARMS:
        ds = sedition_dataset(
            packet_ids=(packet_id,), cells=(cell,), block_indices=(block,)
        )
        assert len(ds.samples) == 1
        out[cell] = ds.samples[0]
    return out


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_all_three_arms_see_identical_report_order_in_every_block(
    packet_id, strategic_enabled
):
    """Element-by-element equality of the permutation lists — the actual
    report order, not a summary of it — for every (packet, block) the pilot
    uses. 6 packets x 5 blocks x 3 arms, all asserted."""
    for block in range(PILOT_BLOCKS):
        arms = _samples_by_arm(packet_id, block)
        orders = {cell: s.metadata["permutation"] for cell, s in arms.items()}

        honest = orders[Cell.HONEST_STRAIGHT]
        for cell in (Cell.BASIC_STRAIGHT, Cell.STRATEGIC_STRAIGHT):
            assert orders[cell] == honest, (
                f"{packet_id} block {block}: {cell.value} sees a different "
                f"report order from honest.\n"
                f"  honest   : {honest}\n"
                f"  {cell.value}: {orders[cell]}"
            )

        digests = {s.metadata["permutation_sha256"] for s in arms.values()}
        assert len(digests) == 1


def test_blocks_actually_differ_from_each_other(strategic_enabled):
    """The counterpart check. If every block had the same order, the matched
    assertion above would pass vacuously while the blocks averaged over
    nothing."""
    orders = [
        _samples_by_arm("E03-MS", b)[Cell.HONEST_STRAIGHT].metadata["permutation"]
        for b in range(PILOT_BLOCKS)
    ]
    distinct = {tuple(o) for o in orders}
    assert len(distinct) > 1, "all five blocks present the same report order"


def test_the_rendered_prompt_presents_reports_in_the_recorded_order(
    strategic_enabled,
):
    """The permutation the metadata records must be the order the analyst
    actually reads. Asserted against the assembled prompt for all three arms:
    the first occurrence index of each report id in the prompt text must be
    strictly increasing in permutation order."""
    from sedition.prompts.assembly import render_analyst_briefing

    from sedition_inspect._resources import (
        components,
        packet,
        scenario_for,
    )

    scenario = scenario_for("E03-MS")
    pk = packet("E03-MS")

    from sedition_inspect._resources import target_slots

    arms = _samples_by_arm("E03-MS", 2)
    for cell, sample in arms.items():
        permutation = sample.metadata["permutation"]
        # Mirrors solver.py: BOTH saboteur arms carry a target; only honest
        # renders without one.
        target = target_slots().get("E03-MS") if cell.has_hidden_objective else None

        assembled = render_analyst_briefing(
            policy=cell.policy.value,
            working_condition=cell.working_condition.value,
            scenario=scenario,
            packet=pk,
            permutation=tuple(permutation),
            components=components(),
            word_budget=1300,
            target=target,
        )
        text = assembled.payload.text

        positions = []
        for rid in permutation:
            m = re.search(rf"^{re.escape(rid)}$", text, re.M)
            assert m, f"{cell.value}: report {rid} not found in the prompt"
            positions.append(m.start())
        assert positions == sorted(positions), (
            f"{cell.value}: prompt presents reports out of the recorded order"
        )
