"""Matched shuffling: five blocks per packet, block 0 canonical, byte-identical
order across cells, fully deterministic from the master seed."""
import pytest

from sedition import SpecViolationError
from sedition.pipeline.blocks import (
    BLOCKS_PER_PACKET,
    BlockRecord,
    build_blocks,
    load_block,
    make_permutation,
    write_block,
)

IDS = tuple(f"E01-SS-R{n:02d}" for n in range(1, 13))
PACKETS = {"E01-SS": IDS}
SEED = 20260814


def test_block_zero_is_canonical_order():
    assert make_permutation(IDS, SEED, "E01", "SS", 0) == IDS


def test_permutations_are_permutations():
    for b in range(BLOCKS_PER_PACKET):
        perm = make_permutation(IDS, SEED, "E01", "SS", b)
        assert sorted(perm) == sorted(IDS)


def test_same_seed_gives_byte_identical_permutations():
    """Two independent builds — as two cells would see — must match exactly."""
    first = build_blocks(PACKETS, SEED)
    second = build_blocks(PACKETS, SEED)
    for block_id in first:
        a = "\x00".join(first[block_id].permutation)
        b = "\x00".join(second[block_id].permutation)
        assert a == b, f"{block_id}: permutation differs between builds"


def test_shuffled_blocks_differ_from_canonical_and_each_other():
    perms = {b: make_permutation(IDS, SEED, "E01", "SS", b)
             for b in range(BLOCKS_PER_PACKET)}
    assert len(set(perms.values())) == BLOCKS_PER_PACKET


def test_different_master_seed_changes_shuffled_blocks_only():
    a = make_permutation(IDS, SEED, "E01", "SS", 3)
    b = make_permutation(IDS, SEED + 1, "E01", "SS", 3)
    assert a != b
    assert make_permutation(IDS, SEED + 1, "E01", "SS", 0) == IDS  # canonical is seed-independent


def test_blocks_are_scoped_to_packet():
    a = make_permutation(IDS, SEED, "E01", "SS", 2)
    b = make_permutation(IDS, SEED, "E01", "MS", 2)
    assert a != b  # different packet, different permutation stream


def test_block_count_is_locked_at_five():
    with pytest.raises(SpecViolationError):
        build_blocks(PACKETS, SEED, blocks_per_packet=10)


def test_persisted_block_roundtrip_is_the_resume_path(tmp_path):
    record = build_blocks(PACKETS, SEED)["E01-SS-b02"]
    write_block(record, tmp_path)
    loaded = load_block("E01-SS-b02", tmp_path)
    assert loaded == record
    assert isinstance(loaded, BlockRecord)
    assert loaded.permutation == record.permutation
