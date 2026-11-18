"""Public-release packet and control-twin naming contracts."""

from __future__ import annotations

import json

import pytest

from sedition.packets.answer_key import PACKET_ID_RE  # noqa: E402
from sedition.packets.build import (  # noqa: E402
    CORE_EVENTS,
    HELDOUT_RENAMED,
    HELDOUT_RETIRED,
    HELDOUT_RUNNABLE,
    HELDOUT_VOID,
)
from sedition.packets.variants import SUBSET_TABLE  # noqa: E402
from sedition.storage.paths import PACKAGE_ROOT, SCENARIOS_DIR, TWINS_DIR  # noqa: E402

RELEASE_EVENTS = ("E01", "E02", "E03")


def _mapping() -> dict:
    return json.loads((PACKAGE_ROOT / "config" / "paper_names.json")
                      .read_text(encoding="utf-8"))


def test_mapping_round_trips() -> None:
    events = _mapping()["events"]
    assert tuple(events) == RELEASE_EVENTS
    assert {event: meta["paper"] for event, meta in events.items()} == {
        event: event for event in RELEASE_EVENTS
    }


def test_the_map_agrees_with_the_one_the_parser_enforces() -> None:
    assert CORE_EVENTS == RELEASE_EVENTS
    assert tuple(_mapping()["events"]) == CORE_EVENTS


def test_release_contains_exactly_three_scenario_sources() -> None:
    sources = sorted(p.name for p in SCENARIOS_DIR.glob("*.md"))
    assert sources == [
        "E01-amber-reach-retention-cell.md",
        "E02-marisol-sandpiper.md",
        "E03-hollis-restraint.md",
    ]


def test_core_events_are_public_release_set() -> None:
    assert CORE_EVENTS == RELEASE_EVENTS


def test_no_extra_event_is_admissible() -> None:
    assert HELDOUT_RUNNABLE == frozenset()
    assert HELDOUT_RENAMED == {}
    assert HELDOUT_RETIRED == {}
    assert HELDOUT_VOID == {}


def test_the_twin_paper_names_are_not_representable_packet_ids() -> None:
    for name in ("E01C", "E02C", "E03C"):
        assert not PACKET_ID_RE.match(f"{name}-SS")
        assert not PACKET_ID_RE.match(f"{name}-MS")
        assert not list(TWINS_DIR.glob(f"{name}*"))
    assert sorted(p.name for p in TWINS_DIR.glob("E0[123]-*-control.json")) == [
        "E01-MS-control.json", "E01-SS-control.json",
        "E02-MS-control.json", "E02-SS-control.json",
        "E03-MS-control.json", "E03-SS-control.json",
    ]


def test_the_twin_paper_names_are_defined_in_exactly_one_place() -> None:
    twins = {meta["twin_paper"] for meta in _mapping()["events"].values()}
    assert twins == {"E01C", "E02C", "E03C"}


def test_mapping_file_contains_only_release_events() -> None:
    raw = _mapping()
    assert set(raw["events"]) == set(RELEASE_EVENTS)
    assert set(raw["variants"]) == {"threat", "control"}
    assert set(raw["forms"]) == {"SS", "MS"}


def test_the_subset_arm_is_closed_rather_than_repointed() -> None:
    from sedition.packets.variants import CONTROL_SUBSET_TABLE, resolve_packet

    assert SUBSET_TABLE == {}
    assert CONTROL_SUBSET_TABLE == {}
    with pytest.raises(ValueError, match="CLOSED"):
        resolve_packet("E01-MS", "subset_benign")
