"""Subprocess target for the kill -9 resume test.

Runs the real Stage 2 shape through `eval_set`, slowly enough that the parent
can destroy it mid-run.

**Why `sedition_mock/slow` and not canned outputs.** `eval_set` keys sample
reuse on a task identifier that hashes `model_args` (see
`_eval/evalset.py:task_identifier`). `get_model("mockllm/model",
custom_outputs=[...])` puts those outputs in `model_args`, so every fresh
construction produces a *different* task identity — and a resume would refuse
the existing log rather than reuse it. The project provider has stable identity
across processes and returns token usage without downloading a tokenizer.

The episodes end up INVALID (mockllm's default text is not parseable officer
JSON) and that is fine: this file measures resume mechanics, not content.

    python tests/inspect_port/_kill_target.py <log_dir> [blocks] [cells]

**Strategic cells.** `require_cell` refuses them while the capability flag is
off, and a subprocess cannot inherit the parent's monkeypatch. The flip is
done HERE, in test-only code, rather than by adding an environment override to
capabilities.py — a production env var that turns the guard off would defeat
the guard for everyone, and the point of the flag is that enabling it is a
deliberate act.
"""
from __future__ import annotations

import sys

from inspect_ai import eval_set

from sedition_inspect.dataset import ALL_PACKETS
from sedition_inspect.mock_model import SLOW_MODEL as MOCK
from sedition_inspect.task import sedition_briefing


def enable_strategic() -> None:
    """Satisfy the capability guard inside THIS process only."""
    import dataclasses

    from sedition_inspect import capabilities

    cap = capabilities.CAPABILITIES["strategic_selection"]
    capabilities.CAPABILITIES["strategic_selection"] = dataclasses.replace(
        cap, available=True
    )


def eval_set_kwargs(log_dir: str, blocks: int = 1,
                    cells: str = "honest_straight") -> dict:
    """Shared by the target and the parent. Every field here is part of the
    task identifier, so the two must agree exactly or resume will not reuse."""
    return dict(
        tasks=[
            sedition_briefing(
                packets=",".join(ALL_PACKETS), cells=cells, blocks=blocks
            )
        ],
        log_dir=log_dir,
        model=MOCK,
        model_roles={"analyst": MOCK, "watch_officer": MOCK, "monitor": MOCK},
        retry_attempts=2,
        display="none",
    )


def main() -> int:
    log_dir = sys.argv[1]
    blocks = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    cells = sys.argv[3] if len(sys.argv) > 3 else "honest_straight"
    if "strategic" in cells:
        enable_strategic()
    success, _logs = eval_set(**eval_set_kwargs(log_dir, blocks, cells))
    print(f"COMPLETED success={success}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
