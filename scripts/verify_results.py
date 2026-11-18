"""Verify the released E01-E03 matrix without raw provider logs or API access."""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "docs/datasets/matrix_480_e01e03.json.gz"
RESULTS = ROOT / "docs/results/matrix-480-2026-08-27"
SUMMARY = RESULTS / "run-summary.json"
EPISODES = RESULTS / "episode_log.jsonl"
EXPECTED_EVENTS = {"E01", "E02", "E03"}
EXPECTED_PACKETS = {f"{event}-{form}" for event in EXPECTED_EVENTS for form in ("MS", "SS")}
EXPECTED_VARIANTS = {"threat", "control"}
EXPECTED_CELLS = {
    "honest_straight",
    "degraded_straight",
    "basic_straight",
    "strategic_straight",
}


def fail(message: str) -> None:
    raise SystemExit(f"release verification failed: {message}")


def load_dataset() -> dict:
    with gzip.open(DATASET, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def verify_sha256() -> None:
    expected = {}
    for line in (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, path = line.split(maxsplit=1)
        expected[path] = digest
    for path, digest in expected.items():
        file = ROOT / path
        if not file.is_file():
            fail(f"checksum target is missing: {path}")
        actual = hashlib.sha256(file.read_bytes()).hexdigest()
        if actual != digest:
            fail(f"checksum mismatch for {path}: expected {digest}, got {actual}")


def recompute_summary(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[f"{row['packet']}|{row['variant']}|{row['cell']}"].append(row)
    out = {}
    for key, group in sorted(groups.items()):
        out[key] = {
            "n": len(group),
            "routine": sum(row["decision"] == "INCLUDE_IN_ROUTINE_UPDATE" for row in group),
            "notify": sum(row["decision"] == "NOTIFY_IMMEDIATELY" for row in group),
            "correct": sum(bool(row["decision_correct"]) for row in group),
            "A_met": sum(row["criterion_A"] == "met" for row in group),
            "B_met": sum(row["criterion_B"] == "met" for row in group),
            "C_met": sum(row["criterion_C"] == "met" for row in group),
            "drs_mean": round(sum(float(row["monitor_drs"]) for row in group) / len(group), 3),
        }
    return out


def main() -> None:
    verify_sha256()
    dataset = load_dataset()
    records = dataset.get("episodes", [])
    if len(records) != 480:
        fail(f"expected 480 full records, found {len(records)}")
    ids = [row["episode_id"] for row in records]
    if len(set(ids)) != 480:
        fail("episode IDs are not unique")
    if {row["event_id"] for row in records} != EXPECTED_EVENTS:
        fail("dataset contains an event outside E01-E03")
    if {row["packet_id"] for row in records} != EXPECTED_PACKETS:
        fail("dataset does not contain exactly the six E01-E03 MS/SS packets")
    if {row["packet_variant"] for row in records} != EXPECTED_VARIANTS:
        fail("dataset does not contain exactly threat and control variants")
    if {row["cell"] for row in records} != EXPECTED_CELLS:
        fail("dataset does not contain exactly the four released analyst conditions")
    if any(row.get("invalid") or row.get("refused") or row.get("error") for row in records):
        fail("dataset contains an invalid, refused, or errored episode")

    compact = [json.loads(line) for line in EPISODES.read_text(encoding="utf-8").splitlines()]
    if len(compact) != 480 or {row["episode_id"] for row in compact} != set(ids):
        fail("compact JSONL and full dataset do not contain the same 480 episodes")
    actual = recompute_summary(compact)
    expected = json.loads(SUMMARY.read_text(encoding="utf-8"))
    if actual != expected:
        fail("run-summary.json does not reproduce from episode_log.jsonl")
    if len(actual) != 48 or {row["n"] for row in actual.values()} != {10}:
        fail("expected 48 cells at n=10")

    print("release verification passed")
    print("  480 unique episodes")
    print("  E01-E03 only; MS/SS; threat/control; four analyst conditions")
    print("  48 cells at n=10")
    print("  checksums and aggregate summary reproduced")


if __name__ == "__main__":
    main()
