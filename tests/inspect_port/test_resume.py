"""Resume, verified against a real SIGKILL.

DECISIONS.md #17 accepted per-sample resume granularity instead of rebuilding
the old harness's per-call idempotency. That trade is only sound if resume
actually works, and "works" has two halves a green unit test would miss:

1. A hard kill leaves a recoverable log — no clean shutdown, no chance to
   finalize, exactly as an OOM or a pulled plug would leave it.
2. On resume, completed samples are *reused* rather than re-run. This is the
   one worth testing carefully, because its failure mode is invisible: the
   run still finishes, the numbers still look fine, and the only symptoms are
   a doubled bill and fresh draws from the model that quietly change the
   distribution the episodes came from.

**A trap these tests exist to pin down.** `eval_set` keys reuse on a task
identifier that hashes `model_args`. Passing `custom_outputs=` to mockllm puts
them in `model_args`, so identity changes on every construction and resume
silently refuses the existing log with a "not associated with a task" error.
Bare model names have stable identity. Real models are unaffected — they carry
no custom_outputs — but anyone testing resume with canned mocks will hit it.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from inspect_ai import eval_set
from inspect_ai.log import list_eval_logs, read_eval_log

from sedition_inspect.dataset import ALL_PACKETS

from ._kill_target import eval_set_kwargs

REPO_ROOT = Path(__file__).resolve().parents[2]
KILL_TARGET = Path(__file__).with_name("_kill_target.py")
EXPECTED_SAMPLES = len(ALL_PACKETS)  # six packets x one cell x one block


def _run(log_dir: Path):
    return eval_set(**eval_set_kwargs(str(log_dir)))


def _latest(log_dir: Path):
    logs = list_eval_logs(str(log_dir))
    assert logs, f"no logs in {log_dir}"
    return read_eval_log(logs[-1].name)


def _model_calls(log) -> int:
    return sum(
        len([e for e in s.events if e.event == "model"]) for s in (log.samples or [])
    )


@pytest.mark.slow
def test_resume_after_sigkill_completes_every_sample(tmp_path):
    log_dir = tmp_path / "killrun"
    proc = subprocess.Popen(
        [sys.executable, str(KILL_TARGET), str(log_dir), "3"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            if list(log_dir.glob("*.eval")):
                break
            if proc.poll() is not None:
                pytest.fail(f"target exited before writing a log:\n{proc.stdout.read()}")
            time.sleep(0.1)
        else:
            pytest.fail("no log file appeared within 60s")

        time.sleep(1.5)   # let some samples finish
        proc.kill()       # TerminateProcess / SIGKILL — nothing gets to clean up
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()

    assert proc.returncode != 0, "the process exited cleanly; it was meant to be killed"
    assert list(log_dir.glob("*.eval")), "the kill left no log at all"

    # Resume the same log_dir. 3 blocks x 6 packets = 18 samples.
    success, logs = eval_set(**eval_set_kwargs(str(log_dir), 3))
    assert success, "resume did not bring the eval set to success"

    # Read the log eval_set returned, not the newest file on disk: the
    # crashed "started" log is deliberately retained for post-mortem and can
    # sort after the resumed one.
    final = read_eval_log(logs[-1].location)
    assert final.status == "success"
    assert len(final.samples) == 18
    ids = {s.id for s in final.samples}
    assert len(ids) == 18, f"duplicate samples after resume: {sorted(ids)}"
    for packet_id in ALL_PACKETS:
        assert f"{packet_id}-b00-honest_straight" in ids


@pytest.mark.slow
def test_completed_eval_set_is_not_rerun(tmp_path):
    """The sharp one: a finished set, re-invoked on the same log_dir, must be
    skipped outright rather than regenerated."""
    log_dir = tmp_path / "reuse"

    success, _ = _run(log_dir)
    assert success
    first = _latest(log_dir)
    assert len(first.samples) == EXPECTED_SAMPLES
    calls_first = _model_calls(first)
    assert calls_first > 0, "first pass made no model calls at all"

    success2, _ = _run(log_dir)
    assert success2

    after = list_eval_logs(str(log_dir))
    assert len(after) == 1, (
        f"a completed task was re-run: {[Path(x.name).name for x in after]}"
    )
    second = read_eval_log(after[-1].name)
    assert second.eval.eval_id == first.eval.eval_id, "the eval was re-executed"
    assert _model_calls(second) == calls_first, "samples were re-generated"


@pytest.mark.slow
def test_sample_identity_and_permutation_are_stable_across_runs(tmp_path):
    """Reuse is keyed on (sample_id, epoch). Ids drifting between runs would
    disable it silently, and the permutation drifting would break matched
    comparison — both invisible without this check."""
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    _run(a_dir)
    _run(b_dir)

    a, b = _latest(a_dir), _latest(b_dir)
    assert {s.id for s in a.samples} == {s.id for s in b.samples}
    assert {s.id: s.metadata["permutation_sha256"] for s in a.samples} == {
        s.id: s.metadata["permutation_sha256"] for s in b.samples
    }


@pytest.mark.slow
def test_resume_after_sigkill_on_a_strategic_cell(tmp_path):
    """The same SIGKILL contract, on the arm that makes four calls.

    A strategic episode differs from an honest one in exactly the way resume
    could get wrong: an extra model call (the selection turn) before the
    briefing, and store fields (attack_decision, rationale) written between
    calls. If a killed-mid-selection sample resumed as a three-call episode,
    it would silently join the run mislabelled. Run whole-or-not-at-all is the
    property under test.

    The capability flag is flipped inside the subprocess (test-only code path
    in _kill_target); it stays False on disk and in this process.
    """
    from sedition_inspect import capabilities

    log_dir = tmp_path / "killrun-strategic"
    proc = subprocess.Popen(
        [sys.executable, str(KILL_TARGET), str(log_dir), "2", "strategic_straight"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            if list(log_dir.glob("*.eval")):
                break
            if proc.poll() is not None:
                pytest.fail(f"target exited before writing a log:\n{proc.stdout.read()}")
            time.sleep(0.1)
        else:
            pytest.fail("no log file appeared within 60s")

        time.sleep(1.5)
        proc.kill()
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()

    assert proc.returncode != 0, "the process exited cleanly; it was meant to be killed"

    # Resume in-process, with the guard satisfied the same test-only way.
    import dataclasses
    original = capabilities.CAPABILITIES["strategic_selection"]
    capabilities.CAPABILITIES["strategic_selection"] = dataclasses.replace(
        original, available=True
    )
    try:
        success, logs = eval_set(
            **eval_set_kwargs(str(log_dir), 2, "strategic_straight")
        )
    finally:
        capabilities.CAPABILITIES["strategic_selection"] = original

    assert success, "resume did not bring the strategic eval set to success"
    final = read_eval_log(logs[-1].location)
    assert final.status == "success"
    assert len(final.samples) == 12  # 6 packets x 2 blocks x 1 cell
    ids = {s.id for s in final.samples}
    assert len(ids) == 12, "duplicate samples after resume"
    assert all(i.endswith("strategic_straight") for i in ids)

    # The flag never moved on disk or in this process's registry.
    assert capabilities.CAPABILITIES["strategic_selection"].available is False
