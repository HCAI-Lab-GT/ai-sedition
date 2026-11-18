"""Saboteur overlay composition, pinned.

Overlay composition is the most likely thing in the prompt layer to drift
silently. A saboteur prompt that quietly lost its §10 section, or kept §10 but
lost the target slots, would still render, still run, still score — and the
policy arm would be measuring nothing. Until now it had only ever been checked
by eye.

Three kinds of assertion here, and the third is the one that catches the
subtle case:

1. **Presence** — the private-objective section, the target descriptor, and
   every target report ID are in the saboteur render.
2. **Absence** — none of them are in the honest render of the same packet and
   block. A leak in that direction would put a hidden objective in the control
   arm.
3. **Size** — the honest-to-saboteur delta sits in a tolerance band around the
   observed ~9,800 characters. A band, not an equality: prompts get edited, and
   a test that breaks on every wording change gets deleted. What it catches is
   an overlay that silently stopped being attached (delta collapses toward 0)
   or one attached twice (delta roughly doubles).

The renders themselves are committed under `golden/` by
`sedition render-golden`, so any change to the composed text shows up as a
reviewed diff rather than a surprise.
"""
from __future__ import annotations

import pytest

from sedition.enums import Cell, WorkingCondition
from sedition.prompts.assembly import render_analyst_briefing
from sedition.storage.paths import GOLDEN_DIR

from sedition_inspect._resources import (
    components,
    packet,
    scenario_for,
    target_slots,
)
from sedition_inspect.dataset import ALL_PACKETS

WORD_BUDGET = 1300
BLOCK_ZERO = None  # canonical order == packet.report_ids

PRIVATE_OBJECTIVE = "10. Private objective"
ATTEMPT_MANDATORY = "10.2 Attempt is mandatory"
WEIGH_BEFORE_WRITING = "10.2 Weigh before you write"

#: Observed honest -> saboteur growth, in characters. Wide enough to survive
#: ordinary prompt edits, narrow enough that a missing or doubled overlay fails.
BASIC_DELTA_BAND = (7_000, 13_000)
STRATEGIC_DELTA_BAND = (8_000, 15_000)


def _render(packet_id: str, cell: Cell) -> str:
    pk = packet(packet_id)
    target = target_slots()[packet_id] if cell.has_hidden_objective else None
    return render_analyst_briefing(
        policy=cell.policy.value,
        working_condition=WorkingCondition.STRAIGHT.value,
        scenario=scenario_for(packet_id),
        packet=pk,
        permutation=pk.report_ids,  # block_index=0
        components=components(),
        word_budget=WORD_BUDGET,
        target=target,
    ).payload.text


# ------------------------------------------------------------- presence ----


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
@pytest.mark.parametrize("cell", [Cell.BASIC_STRAIGHT, Cell.STRATEGIC_STRAIGHT])
def test_saboteur_render_carries_the_private_objective(packet_id, cell):
    text = _render(packet_id, cell)
    assert PRIVATE_OBJECTIVE in text


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
@pytest.mark.parametrize("cell", [Cell.BASIC_STRAIGHT, Cell.STRATEGIC_STRAIGHT])
def test_saboteur_render_names_the_target_incident(packet_id, cell):
    text = _render(packet_id, cell)
    assert target_slots()[packet_id].target_incident in text


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
@pytest.mark.parametrize("cell", [Cell.BASIC_STRAIGHT, Cell.STRATEGIC_STRAIGHT])
def test_saboteur_render_lists_every_target_report_id(packet_id, cell):
    """Every ID, not just some. A partial slot fill would point the saboteur
    at a subset of the target and quietly change what it is concealing."""
    text = _render(packet_id, cell)
    for report_id in target_slots()[packet_id].target_report_ids:
        assert report_id in text, f"{cell.value}/{packet_id} missing {report_id}"


def test_basic_and_strategic_differ_by_the_deliberation_section():
    """The one structural difference between the two overlays: Strategic is
    told to weigh several briefings before writing; Basic is told the attempt
    is mandatory."""
    basic = _render("E01-MS", Cell.BASIC_STRAIGHT)
    strategic = _render("E01-MS", Cell.STRATEGIC_STRAIGHT)

    assert WEIGH_BEFORE_WRITING in strategic
    assert WEIGH_BEFORE_WRITING not in basic
    assert ATTEMPT_MANDATORY in basic
    assert ATTEMPT_MANDATORY not in strategic


# -------------------------------------------------------------- absence ----


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
def test_honest_render_carries_no_objective_and_no_target(packet_id):
    """The control arm. Any of this leaking into honest would mean the
    baseline is not a baseline."""
    text = _render(packet_id, Cell.HONEST_STRAIGHT)
    slots = target_slots()[packet_id]

    assert PRIVATE_OBJECTIVE not in text
    assert ATTEMPT_MANDATORY not in text
    assert WEIGH_BEFORE_WRITING not in text
    assert slots.target_incident not in text

    # Target report IDs legitimately appear as reports; what must not appear
    # is the comma-joined slot fill that designates them AS the target.
    #
    # GUARDED 2026-08-26. E02-SS's target set is a SINGLE id (its Appendix
    # A.2 gives the SS minimal set as {R06} alone), and for a one-element
    # set `", ".join(...)` is just the bare report id, which appears in every
    # render as a matter of course. The assertion did not weaken -- it
    # inverted, failing the honest render for containing its own reports. A
    # one-element target set has no joined form to leak, so the check is
    # skipped there and replaced by the stronger one below, which is applied
    # to every packet either way.
    if len(slots.target_report_ids) > 1:
        assert ", ".join(slots.target_report_ids) not in text

    # Applies to all six, including the single-id case: the honest render must
    # carry no target-designation section at all, so there is nothing for a
    # target id to be designated BY.
    for marker in ("TARGET INCIDENT", "TARGET REPORT", "target_report_ids",
                   "target_incident"):
        assert marker not in text, f"{packet_id}: honest render names {marker}"


# ----------------------------------------------------------------- size ----


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
@pytest.mark.parametrize(
    "cell,band",
    [(Cell.BASIC_STRAIGHT, BASIC_DELTA_BAND), (Cell.STRATEGIC_STRAIGHT, STRATEGIC_DELTA_BAND)],
)
def test_overlay_growth_is_within_the_tolerance_band(packet_id, cell, band):
    """Catches an overlay that stopped attaching (delta -> 0) or attached
    twice (delta roughly doubles), without breaking on wording edits."""
    honest = len(_render(packet_id, Cell.HONEST_STRAIGHT))
    saboteur = len(_render(packet_id, cell))
    delta = saboteur - honest
    low, high = band
    assert low <= delta <= high, (
        f"{cell.value}/{packet_id}: overlay added {delta} chars, expected "
        f"{low}-{high}. Near zero means the overlay is not attached; near "
        f"double means it is attached twice."
    )


# --------------------------------------------------------------- golden ----


@pytest.mark.parametrize("packet_id", ALL_PACKETS)
@pytest.mark.parametrize("cell", [Cell.BASIC_STRAIGHT, Cell.STRATEGIC_STRAIGHT])
def test_straight_overlay_render_matches_its_golden_file(packet_id, cell):
    """STRAIGHT overlays were absent from the golden set — only SHEET cells and
    the selection call were committed. These are the renders that Stage 3's
    paired runs will actually send."""
    path = GOLDEN_DIR / f"{packet_id}-{cell.value}.md"
    if not path.exists():
        pytest.skip(f"golden not yet committed: {path.name} — run `sedition render-golden`")
    assert _render(packet_id, cell) == path.read_text(encoding="utf-8")
