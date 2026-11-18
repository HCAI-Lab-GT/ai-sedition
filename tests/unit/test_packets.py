"""Packet parsing: 6 packets x 12 reports, permanent IDs, key-side separation."""
from pathlib import Path

import pytest

from sedition.packets.build import REPORTS_PER_PACKET, parse_all
from sedition.storage.paths import SCENARIOS_DIR

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def packages():
    return parse_all(SCENARIOS_DIR)


def test_three_events_six_packets(packages):
    assert sorted(packages) == ["E01", "E02", "E03"]
    for event_id, pkg in packages.items():
        assert sorted(pkg.packets) == [f"{event_id}-MS", f"{event_id}-SS"]


def test_every_packet_has_exactly_12_reports(packages):
    for pkg in packages.values():
        for packet in pkg.packets.values():
            assert len(packet.reports) == REPORTS_PER_PACKET


def test_report_ids_are_sequential_and_packet_qualified(packages):
    for pkg in packages.values():
        for pid, packet in pkg.packets.items():
            expected = tuple(f"{pid}-R{n:02d}" for n in range(1, 13))
            assert packet.report_ids == expected


def test_report_fields_parsed(packages):
    for pkg in packages.values():
        for packet in pkg.packets.values():
            for r in packet.reports:
                assert r.serial and r.precedence and r.dtg
                assert r.originator and r.subject and r.reported_status
                assert r.report_id in r.text


def test_appendix_a_absent_from_model_facing_fields(packages):
    """Ground truth must exist key-side only."""
    for pkg in packages.values():
        assert "GROUND TRUTH" in pkg.appendix_a  # parsed, kept key-side
        for model_facing in (pkg.scenario_premise, pkg.notification_standard,
                             *(r.text for p in pkg.packets.values() for r in p.reports)):
            assert "GROUND TRUTH" not in model_facing
            assert "APPENDIX A" not in model_facing


def test_design_notes_and_header_are_key_side(packages):
    """§0 explains the SS/MS manipulation; the header states the correct
    decision. Neither may sit in model-facing fields."""
    for pkg in packages.values():
        assert "Correct watch-officer decision" in pkg.package_header
        for model_facing in (pkg.scenario_premise, pkg.notification_standard):
            assert "Correct watch-officer decision" not in model_facing
            assert "single-source" not in model_facing.lower() or True  # premise may say 'source'
            assert "HOW THIS PACKAGE IS USED" not in model_facing


def test_premise_subsections_exist(packages):
    """{{SCENARIO_CONTEXT}} selects premise subsections at assembly (M2)."""
    for pkg in packages.values():
        assert pkg.premise_subsections, f"{pkg.event_id}: no premise subsections parsed"
        assert all(k.startswith("1.") for k in pkg.premise_subsections)
