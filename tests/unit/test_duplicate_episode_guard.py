"""One logical episode, one record. `eval_set` does not guarantee that.

HOW THE DUPLICATION HAPPENS, read from `inspect_ai/_eval/evalset.py`:

`latest_completed_task_eval_logs` groups the log dir by `eval.task_id`, keeps
the newest file per key and deletes the rest -- except::

    if id_log.header.status != "started":
        fs.rm(id_log.info.name)

A log left in `started` state is deliberately kept for post-mortem debugging
and is never removed by any later run. A task whose args changed gets a
different `task_id` and writes a second log beside the first rather than
resuming it.

`run_two_axis.summarise()` globs `*.eval` and adds up every sample it finds, so
duplicate records can silently inflate a result. These tests use small synthetic
records so the release does not depend on machine-local raw evaluation logs.
"""
from __future__ import annotations

import pytest

from sedition_inspect import run_integrity as RI

import scripts.run_two_axis as R  # noqa: E402  (registers foundry_frozen_flash)

def _record(name: str, task_id: str, status: str, *ids: str,
            mtime: float = 0.0) -> RI.LogRecord:
    """A log header stand-in, for the cases no directory on disk exhibits."""
    return RI.LogRecord(path=f"/logs/probe/{name}", task_id=task_id,
                        status=status, mtime=mtime, episode_ids=tuple(ids))


CLEAN = (
    _record("a.eval", "t1", "success",
            "E01-MS-b5001-honest_straight", "E01-SS-b5001-honest_straight"),
)


# --------------------------------------------------------- anti-vacuity ----

def test_a_clean_log_dir_passes():
    """Every refusal below would also pass against a guard that always
    complained. This is the cell that must be admitted."""
    assert RI.integrity_violations(CLEAN, claimed_blocks=[5001]) == []


def test_a_deliberately_duplicated_episode_id_fails():
    """THE anti-vacuity test named in the task. One id, two log files."""
    records = (
        _record("first.eval", "t1", "success", "E01-MS-b5001-honest_straight"),
        _record("second.eval", "t2", "success", "E01-MS-b5001-honest_straight"),
    )
    found = RI.integrity_violations(records, claimed_blocks=[5001])
    assert any("E01-MS-b5001-honest_straight" in f and "2 log files" in f
               for f in found), found


def test_an_id_repeated_inside_one_log_fails():
    """The other shape of the same defect: one file, the id twice."""
    records = (
        _record("only.eval", "t1", "success",
                "E01-MS-b5001-honest_straight", "E01-MS-b5001-honest_straight"),
    )
    found = RI.integrity_violations(records, claimed_blocks=[5001])
    assert any("appears 2 times inside" in f for f in found), found


def test_two_logs_sharing_a_task_id_fail_even_before_the_ids_are_read():
    """The stale `started` attempt, which is the mechanism rather than the
    symptom. It is reported separately so the message can say what to do."""
    records = (
        _record("old.eval", "t1", "started", "E01-MS-b5001-honest_straight"),
        _record("new.eval", "t1", "success", "E01-MS-b5001-honest_straight",
                mtime=1.0),
    )
    found = RI.integrity_violations(records, claimed_blocks=[5001])
    assert any("task_id t1 has 2 log files" in f for f in found), found
    assert any("never removes" in f for f in found), (
        "the message must explain why eval_set left the file behind")


def test_a_log_with_no_sample_ids_is_a_finding():
    """A guard that cannot see any ids would pass vacuously, which is the same
    class of defect it exists to catch."""
    found = RI.integrity_violations((_record("empty.eval", "t1", "started"),),
                                    claimed_blocks=[5001])
    assert any("records no sample ids" in f for f in found), found


def test_a_log_that_never_reads_raises_by_name(tmp_path, monkeypatch):
    """And it raises LogReadError, not a duplication finding. Reporting "I
    could not read this" as "this holds a duplicate" would send the reader to
    the wrong problem."""
    (tmp_path / "broken.eval").write_bytes(b"not an eval log")
    monkeypatch.setattr(RI, "_READ_BACKOFF", 0.0)
    with pytest.raises(RI.LogReadError, match="broken.eval"):
        RI.scan_log_dir(tmp_path)


# ------------------------------------------------------- blocks and plan ----

def test_a_block_index_the_run_did_not_claim_fails():
    found = RI.integrity_violations(CLEAN, claimed_blocks=[5002])
    assert any("not claimed by this run" in f for f in found), found


def test_a_block_already_spent_in_the_registry_fails():
    """The registry is loaded once, in `run_two_axis.PRIOR_BLOCKS`, and passed
    in. Reusing a spent index reuses that block's report permutation."""
    found = RI.integrity_violations(
        CLEAN, claimed_blocks=[5001], forbidden_blocks=[5001])
    assert any("already spent in the block registry" in f for f in found), found


def test_the_launcher_passes_the_spent_block_registry_to_the_guard():
    """The guard takes the registry as an argument and never loads it.

    `scripts/audit_blocks_spent.py` and `run_two_axis.PRIOR_BLOCKS` stay the
    only readers of blocks_spent.json -- a second loader would be a second
    thing to keep in step, and `test_blocks_spent_registry` already pins that
    one. What has to be checked here is that the launcher actually hands the
    registry over, rather than leaving the parameter at its inert default.
    """
    from pathlib import Path

    jobs = [R.Job("honest_straight", "threat", "foundry_frozen_flash",
                  ("E01-MS",), Path("logs/_no_such_root/honest_straight__threat"))]
    seen: list[frozenset[int]] = []
    original = RI.integrity_violations

    def spy(records, **kw):
        seen.append(frozenset(kw["forbidden_blocks"]))
        return original(records, **kw)

    RI.integrity_violations = spy
    try:
        R.log_integrity_findings(jobs, (5001,))
    finally:
        RI.integrity_violations = original

    assert seen, "log_integrity_findings never called the guard"
    assert seen[0] == R.PRIOR_BLOCKS - {5001}, (
        "the launcher must forbid every index the registry records as spent, "
        "minus the ones this run claims")
    assert len(seen[0]) > 300, (
        f"only {len(seen[0])} forbidden indices; the registry looks truncated")


def test_an_episode_the_plan_never_asked_for_fails():
    """A clobbered or reused log dir: the ids are unique, and wrong."""
    expected = RI.expected_episode_ids(
        packets=["E01-MS"], blocks=[5001], cell="honest_straight",
        variant="threat")
    found = RI.integrity_violations(CLEAN, claimed_blocks=[5001], expected=expected)
    assert any("not planned for this job" in f for f in found), found
    assert any("E01-SS-b5001-honest_straight" in f for f in found), found


def test_a_missing_episode_only_fails_when_the_job_claims_completion():
    """Mid-resume a partly populated dir is normal; after a cell reports
    success it is a replaced record."""
    expected = RI.expected_episode_ids(
        packets=["E01-MS", "E01-SS", "E02-MS"], blocks=[5001],
        cell="honest_straight", variant="threat")
    assert RI.integrity_violations(
        CLEAN, claimed_blocks=[5001], expected=expected) == []
    found = RI.integrity_violations(
        CLEAN, claimed_blocks=[5001], expected=expected, require_complete=True)
    assert any("have no record" in f and "E02-MS" in f for f in found), found


def test_the_variant_is_part_of_the_expected_id():
    """A variant run and a threat run at the same packet, block and cell used to
    collide (sedition/pipeline/episode.py). The expectation must not."""
    threat = RI.expected_episode_ids(
        packets=["E01-MS"], blocks=[5001], cell="honest_straight",
        variant="threat")
    # The legacy spelling canonicalizes: a replayed "ablated" job plans the
    # same ids a fresh "control" job does. Stored logs whose ids still end
    # "-ablated" are mapped at comparison time by canonical_episode_id.
    legacy = RI.expected_episode_ids(
        packets=["E01-MS"], blocks=[5001], cell="honest_straight",
        variant="ablated")
    control = RI.expected_episode_ids(
        packets=["E01-MS"], blocks=[5001], cell="honest_straight",
        variant="control")
    assert threat == {"E01-MS-b5001-honest_straight"}
    assert legacy == control == {"E01-MS-b5001-honest_straight-control"}


# --------------------------------------------------------------- wiring ----

def test_the_launcher_scans_every_job_dir_it_will_write_to():
    """`log_integrity_findings` must cover the plan, not the first job.

    A guard that checks one cell of an eight-cell matrix passes on seven
    corrupted directories.
    """
    from pathlib import Path

    jobs = [
        R.Job(cell, "threat", "foundry_frozen_flash", ("E01-MS",),
              Path("logs/_no_such_root") / f"{cell}__threat")
        for cell in ("honest_straight", "basic_straight")
    ]
    seen: list[str] = []
    original = RI.scan_log_dir

    def spy(log_dir):
        seen.append(str(log_dir))
        return original(log_dir)

    RI.scan_log_dir = spy
    try:
        assert R.log_integrity_findings(jobs, (5001,)) == []
    finally:
        RI.scan_log_dir = original
    assert len(seen) == 2, seen
    assert any("honest_straight__threat" in s for s in seen)
    assert any("basic_straight__threat" in s for s in seen)
