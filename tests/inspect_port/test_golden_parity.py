"""Golden-prompt parity.

The 24 committed renders in `golden/` are the reviewed record of what each
fully-specified analyst call looks like. The port must not change a single
byte of model-facing text: if it does, every prompt-hash in every prior
manifest stops describing the prompt that actually ran.

`sedition render-golden --check` already guards the renderer. What this adds
is that the *port's* path to those renders — going through the setting's
cached resources rather than golden.py's own loaders — produces identical
text. A caching bug that returned a stale component would pass the CLI check
and fail here.
"""
from __future__ import annotations

import pytest

from sedition.enums import Cell, WorkingCondition
from sedition.prompts.assembly import render_analyst_briefing, render_strategic_selection
from sedition.prompts.golden import CORE_CELLS, OVERLAY_VARIANTS
from sedition.storage.paths import GOLDEN_DIR

from sedition_inspect._resources import (
    components,
    packet,
    scenario_for,
    target_slots,
)

PACKET_IDS = (
    "E01-MS", "E01-SS",
    "E02-MS", "E02-SS",
    "E03-MS", "E03-SS",
)
WORD_BUDGET = 1300


def _golden(name: str) -> str:
    path = GOLDEN_DIR / name
    if not path.exists():
        pytest.skip(f"golden file not committed: {name}")
    return path.read_text(encoding="utf-8")


#: 36 per overlay variant x 3 variants (v_current, v_balanced, v8_permissive).
#: 36 = 6 packets x (3 SHEET cells + 2 STRAIGHT overlays + 1 selection).
#: The suffixes are read from golden.py rather than restated, so adding a
#: variant there cannot leave this test asserting a stale count.
GOLDENS_PER_VARIANT = 36
VARIANT_SUFFIXES = tuple(sfx for _ov, sfx in OVERLAY_VARIANTS)
OVERLAY_VARIANT_COUNT = len(VARIANT_SUFFIXES)


def test_the_full_golden_set_is_committed():
    """Both overlay variants are pinned.

    The STRAIGHT overlay renders were added when saboteur composition got its
    own golden coverage; before that only SHEET cells and the selection call
    were pinned, which left the prompts the STRAIGHT-first build order
    actually sends unchecked. The v_balanced set was added when the lever
    menu became a pilot factor — an unpinned variant is a prompt that can
    drift without a diff.
    """
    present = sorted(p.name for p in GOLDEN_DIR.glob("*.md"))
    expected = GOLDENS_PER_VARIANT * OVERLAY_VARIANT_COUNT
    assert len(present) == expected, (
        f"expected {expected} golden renders "
        f"({GOLDENS_PER_VARIANT} per variant x {OVERLAY_VARIANT_COUNT}), "
        f"found {len(present)}")

    for suffix in VARIANT_SUFFIXES:
        if not suffix:
            continue
        variant = [n for n in present if n.endswith(f"{suffix}.md")]
        assert len(variant) == GOLDENS_PER_VARIANT, (
            f"expected {GOLDENS_PER_VARIANT} {suffix} renders, found {len(variant)}")

        # The honest cells carry no overlay, so no variant may touch them.
        for name in variant:
            base = GOLDEN_DIR / name.replace(f"{suffix}.md", ".md")
            if "honest" in name:
                assert base.read_text(encoding="utf-8") == (
                    GOLDEN_DIR / name
                ).read_text(encoding="utf-8"), (
                    f"{name} differs from {base.name} but has no overlay")

    for packet_id in PACKET_IDS:
        for suffix in (
            "honest_sheet", "basic_sheet", "strategic_sheet",
            "basic_straight", "strategic_straight", "strategic_selection",
        ):
            assert f"{packet_id}-{suffix}.md" in present


@pytest.mark.parametrize("packet_id", PACKET_IDS)
@pytest.mark.parametrize("cell", CORE_CELLS)
def test_briefing_render_matches_golden(packet_id: str, cell: Cell):
    """18 core SHEET briefings, rendered through the port's resource cache."""
    pk = packet(packet_id)
    target = target_slots()[packet_id]

    call = render_analyst_briefing(
        policy=cell.policy.value,
        working_condition=WorkingCondition.SHEET.value,
        scenario=scenario_for(packet_id),
        packet=pk,
        permutation=pk.report_ids,  # block 0 = canonical order
        components=components(),
        word_budget=WORD_BUDGET,
        target=target if cell.has_hidden_objective else None,
    )
    assert call.payload.text == _golden(f"{packet_id}-{cell.value}.md")


@pytest.mark.parametrize("packet_id", PACKET_IDS)
def test_strategic_selection_render_matches_golden(packet_id: str):
    """6 selection calls."""
    pk = packet(packet_id)
    call = render_strategic_selection(
        scenario=scenario_for(packet_id),
        packet=pk,
        permutation=pk.report_ids,
        components=components(),
        target=target_slots()[packet_id],
    )
    assert call.payload.text == _golden(f"{packet_id}-strategic_selection.md")


@pytest.mark.parametrize("packet_id", PACKET_IDS)
def test_straight_render_has_no_sheet_section(packet_id: str):
    """STRAIGHT is not in the golden set (only SHEET cells are), so assert its
    defining property directly: no §E, and therefore nothing for the strip
    step to find."""
    from sedition.pipeline.boundary import SHEET_OPEN

    pk = packet(packet_id)
    call = render_analyst_briefing(
        policy="honest",
        working_condition=WorkingCondition.STRAIGHT.value,
        scenario=scenario_for(packet_id),
        packet=pk,
        permutation=pk.report_ids,
        components=components(),
        word_budget=WORD_BUDGET,
        target=None,
    )
    assert SHEET_OPEN not in call.payload.text
    assert "working sheet" not in call.payload.text.lower()
