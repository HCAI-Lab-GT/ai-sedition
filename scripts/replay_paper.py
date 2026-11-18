"""Replay the 480 paper episodes with their archived report orders and token caps."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from sedition_inspect._resources import packet

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/results/matrix-480-2026-08-27/run-manifest.json"
# Each group runs in a separate process so the token overrides stay local.
GROUPS = (
    (("E01", "E03"), "5001-5005,6001-6005", 10000),
    (("E02",), "11001-11005,12001-12005", 8000),
)


def read_orders(manifest: dict) -> dict[str, list[str]]:
    dataset = manifest["dataset"]
    archive = (ROOT / dataset["file"]).read_bytes()
    if hashlib.sha256(archive).hexdigest() != dataset["sha256"]:
        raise ValueError("Paper dataset does not match the run manifest")
    orders = {}
    for row in json.loads(gzip.decompress(archive))["episodes"]:
        pid, block = row["packet_id"], row["block_index"]
        key = f"{pid}:{block}"
        order = row["permutation"]
        digest = hashlib.sha256("\n".join(order).encode()).hexdigest()
        if digest != row["permutation_sha256"] or sorted(order) != sorted(packet(pid).report_ids):
            raise ValueError(f"Invalid archived report order for {key}")
        if orders.setdefault(key, order) != order:
            raise ValueError(f"Conflicting archived report orders for {key}")
    if len(orders) != 60:
        raise ValueError(f"Expected 60 distinct archived report orders, found {len(orders)}")
    return orders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="launch paid Azure evaluations after preflight")
    mode.add_argument("--check-provider", action="store_true", help="also construct Azure clients locally")
    parser.add_argument("--log-root", type=Path, default=Path("logs/paper-replay"))
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    fixed = manifest["fixed"]
    commands = []
    for events, blocks, cap in GROUPS:
        packets = [f"{event}-{form}" for event in events for form in manifest["forms"]]
        cmd = [
            sys.executable, str(ROOT / "scripts/run_two_axis.py"), "--paper-orders",
            "--model-set", manifest["models"]["model_set"],
            "--packets", ",".join(packets), "--blocks", blocks,
            "--cells", ",".join(manifest["analyst_conditions"]),
            "--variants", ",".join(manifest["variants"]), "--overlay", fixed["overlay"],
            "--standard", fixed["notification_standard"], "--officer-version", fixed["officer_version"],
            "--master-seed", str(fixed["master_seed"]), "--threshold-k", str(fixed["threshold_k"]),
            "--selection-mode", fixed["selection_mode"], "--log-root", str(args.log_root / "-".join(events)),
        ]
        if cap == 10000:
            cmd.append("--raised-budgets")
        commands.append(cmd)

    # Validate BOTH groups before the first live request. Preserve the runner's exit code.
    preflight = "--check-provider" if args.run or args.check_provider else "--dry-run"
    for cmd in commands:
        if code := subprocess.call([*cmd, preflight]):
            return code
    print("Verified 60 report orders across 480 planned episodes.", flush=True)
    if args.run:
        for cmd in commands:
            if code := subprocess.call(cmd):
                return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
