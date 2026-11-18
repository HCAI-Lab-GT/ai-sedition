"""The paired probe: one honest episode and one saboteur episode, matched.

Two episodes, same packet, same block. If either of those differs the pair is
not a pair and the comparison means nothing — so both come from one dataset
build, which is what makes the permutation identical by construction.

The default uses E03-MS and straight prompts on both sides. It is a plumbing
probe for matched inputs, model-role wiring, and log inspection, not a powered
behavioral measurement.

    python -m sedition_inspect.paired_run
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from inspect_ai import eval as inspect_eval

from .provider_support import missing_env
from .run import MODEL_SETS, build_model_roles
from .task import sedition_briefing

PACKET = "E03-MS"
CELLS = "honest_straight,basic_straight"

#: `--model-set real` used to select a role table hardcoded in this file, a
#: duplicate of run.py's "gpt-4.1" entry that could drift from it silently.
#: The sets now come from run.py, so every set defined there — including
#: foundry_llama — is selectable here with no change. The old name is kept as
#: an alias so existing invocations and notes still work.
ALIASES = {"real": "gpt-4.1"}


def load_env(*candidates: Path) -> None:
    """Populate os.environ from the first .env files that define a value.

    Deliberately says nothing about WHICH keys are needed — that depends on
    the model set, and is checked separately against the providers actually
    selected.
    """
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="The honest/saboteur paired probe.")
    p.add_argument("--model-set", default="gpt-4.1",
                   choices=sorted({*MODEL_SETS, *ALIASES}))
    p.add_argument("--log-dir", default="logs/paired")
    args = p.parse_args(argv)
    model_set = ALIASES.get(args.model_set, args.model_set)

    root = Path(__file__).resolve().parents[2]
    load_env(root / ".env", root.parent / ".env")
    absent = missing_env(
        (m for m, _ in MODEL_SETS[model_set].values()), os.environ
    )
    if absent:
        print(f"Missing credentials for model set {model_set!r}:")
        for line in absent:
            print(f"  {line}")
        print("Put them in .env and retry.")
        return 2

    roles = build_model_roles(model_set)
    logs = inspect_eval(
        sedition_briefing(packets=PACKET, cells=CELLS, blocks=1),
        model=roles["analyst"],
        model_roles=roles,
        log_dir=args.log_dir,
        max_connections=2,
    )
    log = logs[0]
    print(f"\nstatus  : {log.status}")
    print(f"samples : {len(log.samples or [])}")
    print(f"log     : {log.location}")
    print("\nNow run the checks:")
    print(f"  python -m sedition_inspect.analyze_log {log.location}")
    return 0 if log.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
