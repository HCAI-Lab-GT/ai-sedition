"""Matched blocks and deterministic report permutations.

A matched block is (event, version, block_index). It owns exactly one report
permutation; every cell in that block sees the reports in that identical
order. Five blocks per packet (locked): block 0 is canonical order, blocks
1-4 are deterministic shuffles derived from the master seed.

Permutations are persisted with the block record. On resume they are LOADED,
never regenerated — regeneration is only for initial creation and for the
determinism test.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import HarnessError, SpecViolationError

BLOCKS_PER_PACKET = 5  # locked: block 0 canonical + 4 shuffled


def block_seed(master_seed: int, event: str, version: str, block_index: int) -> int:
    """Deterministic per-block seed: SHA256 over the identifying tuple."""
    key = f"{master_seed}|{event}|{version}|{block_index}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)


def make_permutation(report_ids: tuple[str, ...], master_seed: int,
                     event: str, version: str, block_index: int) -> tuple[str, ...]:
    """Permutation of presentation positions. Report IDs are immutable identity."""
    if block_index == 0:
        return tuple(report_ids)  # canonical published order
    rng = random.Random(block_seed(master_seed, event, version, block_index))
    ids = list(report_ids)
    # Explicit Fisher-Yates so the algorithm is pinned here, not in library internals.
    for i in range(len(ids) - 1, 0, -1):
        j = rng.randrange(i + 1)
        ids[i], ids[j] = ids[j], ids[i]
    return tuple(ids)


@dataclass(frozen=True)
class BlockRecord:
    block_id: str            # e.g. "E02-MS-b03"
    event: str
    version: str
    block_index: int
    master_seed: int
    permutation: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @staticmethod
    def from_json(text: str) -> BlockRecord:
        d = json.loads(text)
        d["permutation"] = tuple(d["permutation"])
        return BlockRecord(**d)


def build_blocks(report_ids_by_packet: dict[str, tuple[str, ...]],
                 master_seed: int,
                 blocks_per_packet: int = BLOCKS_PER_PACKET) -> dict[str, BlockRecord]:
    """Create every block record for a run. Keyed by block_id."""
    if blocks_per_packet != BLOCKS_PER_PACKET:
        raise SpecViolationError(
            f"blocks_per_packet must be {BLOCKS_PER_PACKET} (locked: five matched blocks)"
        )
    blocks: dict[str, BlockRecord] = {}
    for packet_id, report_ids in sorted(report_ids_by_packet.items()):
        event, version = packet_id.split("-")
        for b in range(blocks_per_packet):
            perm = make_permutation(report_ids, master_seed, event, version, b)
            if sorted(perm) != sorted(report_ids):
                raise HarnessError(f"permutation for {packet_id}-b{b:02d} is not a permutation")
            block_id = f"{packet_id}-b{b:02d}"
            blocks[block_id] = BlockRecord(
                block_id=block_id, event=event, version=version,
                block_index=b, master_seed=master_seed, permutation=perm,
            )
    return blocks


def write_block(record: BlockRecord, directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.block_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(record.to_json(), encoding="utf-8")
    tmp.replace(path)
    return path


def load_block(block_id: str, directory: str | Path) -> BlockRecord:
    """Load a stored block. This — not regeneration — is the resume path."""
    path = Path(directory) / f"{block_id}.json"
    if not path.exists():
        raise HarnessError(
            f"block record {block_id} not found in {directory}; "
            "blocks must be created and persisted before episodes run"
        )
    return BlockRecord.from_json(path.read_text(encoding="utf-8"))
