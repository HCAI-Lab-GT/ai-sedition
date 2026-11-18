"""Run the section 18.4 ablation gate over a candidate twin.

    python -m sedition.packets.control_gate_cli E03-MS path/to/twin.json
    python -m sedition.packets.control_gate_cli --self-test

(Formerly ablation_gate_cli; renamed 2026-08-27 with the ablated->control
vocabulary change. PREREGISTRATION references to the old module path are
historical.)

The twin file is JSON: either a list of reports, or an object with a "reports"
key, each report an object with a "text" field -- the same shape the packet
build already emits, so an author can copy a packet out of build/packets.json,
edit it, and run this against it.

Exit status is 0 on PASS, 1 on BLOCKED, 2 on a usage or load error, so this can
sit in a loop or a CI step.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sedition.packets.control_gate import evaluate_ablation, format_report
from sedition.storage.paths import PACKETS_JSON


def _load_reports(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("reports", data)
    if not isinstance(data, list) or not data:
        raise ValueError(
            f"{path}: expected a non-empty list of reports, or an object with a "
            f"'reports' key holding one"
        )
    for i, r in enumerate(data):
        if not isinstance(r, dict) or not str(r.get("text", "")).strip():
            raise ValueError(f"{path}: report {i} has no non-empty 'text' field")
    return data


def _self_test(vocab) -> int:
    """Run the gate over the UN-ablated threat packets.

    Every one must be BLOCKED with CRITERION_SURVIVES. A gate that passed the
    packets it is supposed to reject would pass anything.
    """
    packets = json.loads(PACKETS_JSON.read_text(encoding="utf-8"))
    checked = failures = 0
    for scenario in packets.values():
        for pid, packet in scenario.get("packets", {}).items():
            report = evaluate_ablation(pid, packet["reports"], vocabulary=vocab)
            checked += 1
            survives = [
                f for f in report.facts if f.verdict.value == "CRITERION_SURVIVES"
            ]
            ok = not report.passed and survives
            if not ok:
                failures += 1
            print(
                f"  {pid:8s} {'REJECTED (correct)' if ok else 'ACCEPTED (WRONG)':20s}"
                f"  {len(survives)}/{len(report.facts)} facts still form"
            )
    if not checked:
        print("SELF-TEST VACUOUS: no packets loaded", file=sys.stderr)
        return 2
    print(f"\n  {checked} threat packets checked, {failures} wrongly accepted")
    return 0 if failures == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("packet_id", nargs="?", help='source packet, e.g. "E03-MS"')
    ap.add_argument("twin", nargs="?", type=Path, help="JSON file of ablated reports")
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="check the gate rejects the un-ablated threat packets",
    )
    args = ap.parse_args(argv)

    from sedition_inspect.scorers import vocabulary

    vocab = vocabulary()

    if args.self_test:
        print("ABLATION GATE SELF-TEST - the gate must REJECT every threat packet\n")
        return _self_test(vocab)

    if not args.packet_id or not args.twin:
        ap.error("packet_id and twin are both required unless --self-test is given")
    try:
        reports = _load_reports(args.twin)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        report = evaluate_ablation(args.packet_id, reports, vocabulary=vocab)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
