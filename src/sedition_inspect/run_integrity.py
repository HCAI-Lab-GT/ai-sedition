"""Two records for one logical episode, and the ways `eval_set` produces them.

HOW RESUME ACTUALLY WORKS, read from `inspect_ai/_eval/evalset.py`:

* Every log in `log_dir` is keyed by `eval.task_id`, which is derived from the
  task name, its task args, the model and the eval-set args
  (`task_identifier`). `latest_completed_task_eval_logs` groups by that key and
  keeps the newest file by mtime.
* With `retry_cleanup` on -- the default, and `scripts/run_two_axis.py` does
  not turn it off -- the older files for a key are deleted. **Except**::

      if id_log.header.status != "started":
          fs.rm(id_log.info.name)

  A log left in `started` state is deliberately kept "in case its needed for
  post-mortum debugging". A process that was killed mid-episode leaves exactly
  that, and it is never cleaned up by any later run.
* A task whose args changed gets a DIFFERENT `task_id`, so it does not resume
  the old log -- it writes a second one alongside it. `eval_set` normally
  refuses a log dir holding a log it cannot map to a task, but only when
  `log_dir_allow_dirty` is off and only for logs already present at the start
  of the call.

BOTH FAILURE MODES ARE ON DISK IN THIS REPOSITORY:

    logs/rung6/b17          two files, one task_id, BOTH status=started
    logs/rung4/b9           started + success, same task_id
    logs/baseline-sheet/b14 started + success, same task_id
    logs/v8-forced/b35      two files, two task_ids, BOTH status=success,
                            byte-identical task args, and the SAME two sample
                            ids -- two complete records of the same two
                            episodes

Nothing noticed. `run_two_axis.summarise()` globs `*.eval` and adds up every
sample it finds, so a stale sibling inflates the sample count and the decision
tally of the cell it sits in; the analysis scripts glob the same way. An
episode counted twice is not a loud failure, it is a slightly different number.

THE GUARD. This module reads the log headers only -- no samples, no model
calls -- and reports:

* an episode id present in more than one log file, or twice in one file;
* two log files sharing a `task_id` (a superseded attempt that survived);
* a block index in the logs that the run never claimed;
* a claimed block index that a prior run already spent, when the caller passes
  the spent-block registry;
* an episode id the plan did not ask for (a clobbered or reused log dir);
* a log whose header yields no episode ids at all, because a guard that cannot
  see any ids would otherwise pass vacuously.

Missing episodes are reported separately and only raise when the caller says
the dir should be complete: mid-resume, missing is the normal state.

A file that cannot be READ is not one of those findings. It raises
`LogReadError` after a bounded retry, so an unreadable log is never reported as
a duplicate and a duplicate is never explained away as an unreadable log.

This module does not know about `sedition/config/blocks_spent.json`. The
registry is loaded once, in `scripts/run_two_axis.PRIOR_BLOCKS`, and passed in
-- `tests/unit/test_blocks_spent_registry.py` asserts that
`PRIOR_BLOCKS` is derived from the registry, and a second loader here would be
a second thing to keep in step.
"""
from __future__ import annotations

import dataclasses
import re
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

from sedition.packets.variants import canonical_variant
from sedition.pipeline.episode import episode_id

from inspect_ai.log import read_eval_log

#: Block index inside an episode id, e.g. `E01-MS-b5001-honest_straight`. The
#: same expression `scripts/audit_blocks_spent.py` and
#: `tests/unit/test_blocks_spent_registry.py` use, so the three agree
#: about what a block index looks like.
_BLOCK_IN_ID = re.compile(r"-b(\d+)-")

def canonical_episode_id(eid: str) -> str:
    """An episode id with any legacy variant suffix in the current spelling.

    Ids are EXTERNAL data here -- they are read out of log headers -- and ids
    committed before 2026-08-27 end in the legacy variant vocabulary
    ("...-ablated"). The stored bytes are immutable; this maps them for
    comparison and display so a legacy log still matches the plan that
    produced it. Ids with no variant suffix (threat episodes) pass through.
    """
    head, sep, tail = eid.rpartition("-")
    if not sep:
        return eid
    # The variant, when present, is the final hyphen-separated segment and
    # carries no hyphens itself ("ablated", "subset_control", ...); cells and
    # packet ids never spell a legacy variant, so an id without a variant
    # suffix maps to itself.
    canon = canonical_variant(tail)
    return eid if canon == tail else f"{head}-{canon}"


#: Attempts per log header before a read is called a failure.
#:
#: A read that fails once is not evidence of a corrupt log. Sweeping the 56
#: logs under the manifested run roots raised one failure on
#: `logs/pilot144/benign_error__subset_benign`, and that same file then read
#: cleanly 40 times in a row and on every later sweep -- this checkout sits on a
#: synced drive, where a transient lock is a normal event. Retried rather than
#: reported, because "I could not read this file" and "this directory holds a
#: duplicate" are different facts, and a launcher that refuses on the first is
#: refusing for a reason that has nothing to do with the data.
READ_ATTEMPTS = 3

#: Seconds to wait before retry N. Short: this guards against a lock held for
#: an instant, not against a filesystem that is down.
_READ_BACKOFF = 0.25


class DuplicateEpisodeRecords(RuntimeError):
    """A log directory holds two records for one logical episode, or a record
    the run never planned. Raised, never warned: the numbers downstream are
    already wrong by the time anyone reads a warning.
    """


class LogReadError(RuntimeError):
    """A log file in a run directory could not be read.

    Kept distinct from `DuplicateEpisodeRecords` so an unreadable file is never
    reported as a duplication finding, and so a real corruption is never
    absorbed as one either.
    """


def _read_header(path: Path):
    """Read one log header, retrying a transient failure.

    Args:
        path: The `.eval` file to read.

    Returns:
        The log header, as `read_eval_log(header_only=True)` returns it.

    Raises:
        LogReadError: If every attempt fails, naming the file and the last
            underlying exception.
    """
    last: Exception | None = None
    for attempt in range(READ_ATTEMPTS):
        try:
            return read_eval_log(str(path), header_only=True)
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised by name
            last = exc
            if attempt + 1 < READ_ATTEMPTS:
                time.sleep(_READ_BACKOFF * (attempt + 1))
    raise LogReadError(
        f"{path} could not be read in {READ_ATTEMPTS} attempts: "
        f"{type(last).__name__}: {last}. The episode-record guard cannot check "
        f"a directory it cannot read; repair or quarantine this file."
    ) from last


@dataclasses.dataclass(frozen=True)
class LogRecord:
    """One `.eval` file, read from its header.

    Attributes:
        path: Path to the log file, as a string.
        task_id: `eval.task_id`, the key `eval_set` groups and resumes on.
        status: `started`, `success`, `cancelled` or `error`.
        mtime: Last-write time, used only to name the newer file in a report.
        episode_ids: Sample ids recorded in the log header, in file order.
    """

    path: str
    task_id: str
    status: str
    mtime: float
    episode_ids: tuple[str, ...]


def scan_log_dir(log_dir: Path | str) -> list[LogRecord]:
    """Read every `.eval` header in one job's log directory.

    Args:
        log_dir: Directory `eval_set` was pointed at for a single job.

    Returns:
        One `LogRecord` per `.eval` file, sorted by file name. An empty list
        when the directory does not exist, which is the normal state before a
        run starts.

    Raises:
        LogReadError: If a file cannot be read after `READ_ATTEMPTS` tries.
    """
    out: list[LogRecord] = []
    base = Path(log_dir)
    if not base.is_dir():
        return out
    for f in sorted(base.glob("*.eval")):
        log = _read_header(f)
        dataset = log.eval.dataset if log.eval else None
        ids = tuple(str(s) for s in (dataset.sample_ids or [])) if dataset else ()
        out.append(LogRecord(
            path=str(f),
            task_id=str(log.eval.task_id) if log.eval else "<no-eval-header>",
            status=str(log.status),
            mtime=f.stat().st_mtime,
            episode_ids=ids,
        ))
    return out


def expected_episode_ids(
    *, packets: Sequence[str], blocks: Sequence[int], cell: str, variant: str
) -> frozenset[str]:
    """The episode ids one job is planned to produce.

    Built with `sedition.pipeline.episode.episode_id`, the same function
    `dataset.build_sample` stamps onto `Sample.id`, so the expectation cannot
    drift from the id scheme.

    Args:
        packets: Packet ids, e.g. `("E01-SS", "E01-MS")`.
        blocks: Block indices the run declared.
        cell: Matrix cell id, e.g. `"honest_straight"`.
        variant: Packet variant, e.g. `"threat"` or `"control"`. Legacy
            spellings ("ablated") are canonicalized, so a replayed command
            plans the ids a fresh run would produce. ("subset_benign" was
            also legal until the subset arm was closed on 2026-08-26; see
            sedition.packets.variants.SUBSET_TABLE.)

    Returns:
        Every id the job's dataset should contain.
    """
    variant = canonical_variant(variant)
    out: set[str] = set()
    for packet_id in packets:
        event_id, version = packet_id.split("-", 1)
        for block in blocks:
            out.add(episode_id(event_id, version, block, cell, variant))
    return frozenset(out)


def blocks_in(episode_ids: Iterable[str]) -> set[int]:
    """Block indices recovered from a collection of episode ids.

    Args:
        episode_ids: Episode ids as they appear in a log header.

    Returns:
        Every block index parsed out. Ids that carry none are skipped; a log
        that yields no ids at all is reported by `integrity_violations`.
    """
    found: set[int] = set()
    for eid in episode_ids:
        match = _BLOCK_IN_ID.search(eid)
        if match:
            found.add(int(match.group(1)))
    return found


def integrity_violations(
    records: Sequence[LogRecord],
    *,
    claimed_blocks: Iterable[int],
    expected: frozenset[str] | None = None,
    forbidden_blocks: Iterable[int] = (),
    require_complete: bool = False,
) -> list[str]:
    """Every way this log directory misrepresents the episodes it holds.

    Args:
        records: Headers read by `scan_log_dir`.
        claimed_blocks: The block indices the run declared on the command line.
        expected: Episode ids the job planned to produce, from
            `expected_episode_ids`. `None` skips the plan comparison, which is
            what a caller does when it only wants the duplication checks.
        forbidden_blocks: Indices a prior run already spent, normally
            `run_two_axis.PRIOR_BLOCKS` minus this run's own claim. An episode
            on one of these reuses a report permutation and silently breaks the
            matched comparison.
        require_complete: Treat a planned episode with no record as a
            violation. False mid-resume, True once a job has reported success.

    Returns:
        One line per finding, empty when the directory is sound.
    """
    claimed = set(claimed_blocks)
    forbidden = set(forbidden_blocks)
    out: list[str] = []

    by_task: dict[str, list[LogRecord]] = defaultdict(list)
    for rec in records:
        by_task[rec.task_id].append(rec)
    for task_id, group in sorted(by_task.items()):
        if len(group) > 1:
            names = ", ".join(
                f"{Path(r.path).name} [{r.status}]"
                for r in sorted(group, key=lambda r: r.mtime))
            out.append(
                f"task_id {task_id} has {len(group)} log files: {names}. "
                f"eval_set keeps only the newest per task_id and deletes the "
                f"rest -- except logs left in 'started' state, which it never "
                f"removes. Quarantine the superseded file(s) before running.")

    where: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        if not rec.episode_ids:
            out.append(
                f"{Path(rec.path).name} [{rec.status}] records no sample ids; "
                f"this guard cannot see what it holds and would pass vacuously")
        seen: dict[str, int] = defaultdict(int)
        for eid in rec.episode_ids:
            # Canonicalized so a legacy "-ablated" record and a resumed
            # "-control" record of the same logical episode collide here
            # instead of being counted as two episodes.
            eid = canonical_episode_id(eid)
            seen[eid] += 1
            where[eid].append(Path(rec.path).name)
        for eid, n in sorted(seen.items()):
            if n > 1:
                out.append(
                    f"episode {eid} appears {n} times inside "
                    f"{Path(rec.path).name}")

    for eid, files in sorted(where.items()):
        if len(set(files)) > 1:
            out.append(
                f"episode {eid} has a record in {len(set(files))} log files: "
                f"{', '.join(sorted(set(files)))}. Every downstream tally globs "
                f"*.eval and would count it more than once.")

    found_ids = set(where)
    found_blocks = blocks_in(found_ids)
    unclaimed = sorted(found_blocks - claimed)
    if unclaimed:
        out.append(
            f"block indices {unclaimed} appear in the logs but were not claimed "
            f"by this run (claimed {sorted(claimed)})")
    collided = sorted(found_blocks & forbidden)
    if collided:
        out.append(
            f"block indices {collided} appear in the logs and are already spent "
            f"in the block registry; those episodes reuse a prior run's report "
            f"permutation")

    if expected is not None:
        unplanned = sorted(found_ids - expected)
        if unplanned:
            out.append(
                f"{len(unplanned)} episode id(s) in the logs were not planned "
                f"for this job: {unplanned[:8]}"
                f"{' ...' if len(unplanned) > 8 else ''}. The log dir belongs to "
                f"a different cell, variant or block set.")
        if require_complete:
            missing = sorted(expected - found_ids)
            if missing:
                out.append(
                    f"{len(missing)} planned episode(s) have no record: "
                    f"{missing[:8]}{' ...' if len(missing) > 8 else ''}")
    return out


def assert_unique_episode_records(
    log_dir: Path | str,
    *,
    claimed_blocks: Iterable[int],
    expected: frozenset[str] | None = None,
    forbidden_blocks: Iterable[int] = (),
    require_complete: bool = False,
) -> list[LogRecord]:
    """Scan a job's log directory and raise unless every episode is recorded once.

    Args:
        log_dir: Directory `eval_set` was pointed at for a single job.
        claimed_blocks: The block indices the run declared.
        expected: Episode ids the job planned to produce, or `None` to skip the
            plan comparison.
        forbidden_blocks: Indices a prior run already spent.
        require_complete: Treat a planned episode with no record as a violation.

    Returns:
        The records that were scanned, so a caller can report on them.

    Raises:
        DuplicateEpisodeRecords: If `integrity_violations` finds anything.
    """
    records = scan_log_dir(log_dir)
    bad = integrity_violations(
        records,
        claimed_blocks=claimed_blocks,
        expected=expected,
        forbidden_blocks=forbidden_blocks,
        require_complete=require_complete,
    )
    if bad:
        raise DuplicateEpisodeRecords(
            f"{log_dir}: {len(bad)} episode-record violation(s):"
            "\n    " + "\n    ".join(bad))
    return records
