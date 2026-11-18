"""The spent-block registry must not fall behind the logs again.

WHY THIS EXISTS. A block index owns a report permutation
(sedition/pipeline/blocks.py). Reusing one across runs reuses that permutation,
so two runs that believe they are independent share presentation order. The
failure is invisible: every episode completes, every log looks healthy, and the
matched comparison is quietly gone.

`run_two_axis.PRIOR_BLOCKS` was a hand-maintained literal and had fallen **161
indices behind** what the logs actually showed -- 75 declared against 200 on
disk, with the entire 3101-3110 threat half undeclared. Nothing caught it,
because the disjointness assertion was measuring the run against a stale set and
passing.

THE CONTRACT:
  * the registry is a committed file, not a literal maintained by memory;
  * it is a SUPERSET of every block index found in logs/;
  * ranges whose logs were deleted stay declared -- they cannot be rediscovered,
    so a disk-derived registry would silently free them for reuse;
  * PRIOR_BLOCKS is built from the registry, so the two cannot diverge.

The disk scan here reads headers only, and only the newest logs, so it stays a
unit test. The authority is `scripts/audit_blocks_spent.py`, which reads every
log and runs in CI.
"""
from __future__ import annotations

import json
import re

import pytest

from sedition.storage.paths import PACKAGE_ROOT, REPO_ROOT

REGISTRY = PACKAGE_ROOT / "config" / "blocks_spent.json"

#: Ranges whose logs are gone. Named individually because a count would not
#: notice which one went, and nothing on disk can put them back.
DELETED_LOG_RANGES = (*range(2001, 2011), 3001, 3002)

#: The 240-episode threat column. The ablated twins are compared against it, so
#: landing on one of its blocks would make the comparison self-referential.
THREAT_240 = tuple(range(3101, 3111))

#: Ranges declared on branches main cannot see. A scan of main's logs finds
#: none of these, which is exactly how the registry went 161 indices stale:
#: unpushed main plus an unmerged branch means neither side can see what the
#: other has spent, and the collision only appears at merge, silently.
CLAIMED_ON_BRANCHES = (
    50,                       # envtest, run_rung.py rungN
    *range(151, 188),         # envtest, strat-dev-2026-08-22
    *range(721, 723),         # historical development allocation
    *range(730, 750),         # historical reproduction allocation
    *range(831, 836),         # historical reproduction allocation
)


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _expand(rs) -> set[int]:
    return {b for a, z in rs for b in range(a, z + 1)}


def _spent() -> set[int]:
    return _expand(_registry()["all_spent"])


def test_the_registry_exists_and_is_not_empty():
    """Anti-vacuity: every assertion below passes on an empty registry."""
    assert REGISTRY.exists(), f"{REGISTRY} is missing"
    spent = _spent()
    assert len(spent) > 300, f"only {len(spent)} spent indices; the registry looks truncated"


def test_prior_blocks_is_built_from_the_registry():
    from scripts.run_two_axis import PRIOR_BLOCKS

    assert set(PRIOR_BLOCKS) == _spent(), (
        "PRIOR_BLOCKS and the registry have diverged; PRIOR_BLOCKS must be derived "
        "from sedition/config/blocks_spent.json, never restated as a literal")


@pytest.mark.parametrize("block", DELETED_LOG_RANGES)
def test_a_deleted_log_range_stays_reserved(block):
    """These cannot be rediscovered by scanning. If the registry is ever
    regenerated from disk alone they silently become free for reuse."""
    assert block in _spent(), (
        f"block {block} had its logs deleted and is no longer reserved -- a future "
        f"run can now land on it and reuse its permutation")


@pytest.mark.parametrize("block", THREAT_240)
def test_the_threat_column_blocks_stay_reserved(block):
    assert block in _spent(), (
        f"block {block} belongs to the 240-episode threat column (PREREGISTRATION 68); "
        f"reusing it would make the ablated comparison self-referential")


def test_the_registry_covers_every_block_index_on_disk():
    """The regression, stated directly.

    Block indices live in each log's sample ids, NOT in its filename, so this
    reads log headers. An earlier version scanned filenames, recovered nothing,
    and skipped -- a guard that skips forever is a vacuous pass, which is the
    same class of defect it was written to catch. Bounded to the newest logs so
    it stays a unit test; `scripts/audit_blocks_spent.py` reads all of them and
    runs in CI.
    """
    from inspect_ai.log import read_eval_log

    logs = REPO_ROOT / "logs"
    if not logs.is_dir():
        pytest.skip("no logs/ directory in this checkout")
    files = sorted(logs.rglob("*.eval"), key=lambda f: f.stat().st_mtime, reverse=True)
    assert files, "logs/ exists but holds no .eval files; this guard cannot do its job"

    found: set[int] = set()
    read = 0
    for f in files[:40]:
        try:
            lg = read_eval_log(str(f), header_only=True)
        except Exception:
            continue
        read += 1
        ds = lg.eval.dataset if lg.eval else None
        for sid in (ds.sample_ids or []) if ds else []:
            m = re.search(r"-b(\d+)-", str(sid))
            if m:
                found.add(int(m.group(1)))

    assert read, "no log header could be read; the guard would pass vacuously"
    assert found, (
        f"read {read} log headers and recovered no block index -- the sample-id "
        f"format changed and this guard has stopped checking anything")

    missing = sorted(found - _spent())
    assert not missing, (
        f"{len(missing)} block indices appear in logs/ but are not in the registry: "
        f"{missing[:20]} -- run `python scripts/audit_blocks_spent.py --write`")


@pytest.mark.parametrize("block", CLAIMED_ON_BRANCHES)
def test_a_branch_claimed_range_stays_reserved(block):
    """No scan of main can rediscover these. If the registry is ever rebuilt
    from main's logs alone they silently become free, and the collision only
    surfaces when the branch merges -- by which point both runs are scored."""
    assert block in _spent(), (
        f"block {block} is claimed on an unmerged branch and is no longer "
        f"reserved on main; run `python scripts/audit_branch_blocks.py`")


def test_the_declared_and_deleted_ranges_are_recorded_separately():
    """Provenance has to survive. A flat list of integers cannot say which
    entries are unrecoverable from disk, which is the whole reason the file is
    committed rather than derived."""
    reg = _registry()
    for key in ("on_disk", "declared_no_logs", "deleted_logs",
                "claimed_on_branches", "all_spent"):
        assert key in reg, f"registry lost its {key!r} provenance section"
    assert _expand(reg["deleted_logs"]) == set(DELETED_LOG_RANGES)
    assert _expand(reg["all_spent"]) >= _expand(reg["on_disk"])
    assert _expand(reg["all_spent"]) >= _expand(reg["deleted_logs"])
    assert _expand(reg["all_spent"]) >= _expand(reg["claimed_on_branches"])


def test_a_fresh_range_above_the_high_water_mark_is_actually_fresh():
    """The guard must be able to say yes, or it is just an obstacle."""
    spent = _spent()
    high = max(spent)
    assert not (set(range(high + 1, high + 11)) & spent)
