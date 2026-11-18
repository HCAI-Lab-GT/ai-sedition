"""Stage 0: the gpt-4.1 strategic baseline, on the unmodified v6 selection prompt.

Establishes something nobody has measured. The 299/300 ABSTAIN result is a fact
about the DeepSeek stack; per PREREGISTRATION.md section 4 families never pool,
so it is not a baseline for gpt-4.1 and cannot be used as the control arm for a
gpt-4.1 v8 comparison. This run supplies that control.

It also answers a prior question cheaply: whether gpt-4.1 abstains at all. If it
does not, the v8 revision targets a DeepSeek-shaped problem this family does not
have, and that is worth knowing before authoring against it.

Prompts are UNMODIFIED v6 -- this is the control, so nothing here may differ from
the published arm except the model seats.

    python scripts/run_gpt_strategic.py                  # 30 episodes, one cell
    python scripts/run_gpt_strategic.py --cells strategic_straight,strategic_sheet
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sedition.storage.paths import PROMPT_MODULES_DIR  # noqa: E402
from sedition_inspect.dataset import ALL_PACKETS, DEFAULT_MASTER_SEED  # noqa: E402
from sedition_inspect.run import MODEL_SETS, run_matrix  # noqa: E402

#: Same family as run-gpt-pilot-01, different arm. Pools with neither the
#: DeepSeek nor the Llama record.
FAMILY = "gpt-pilot"
#: Overlay keys were renamed on merge into main -- "v8" collided with an
#: unrelated v8 lineage already on main. See PREREGISTRATION 48.
ARMS = {"current": "strategic_v6_baseline",
        "ev": "strategic_ev_full",
        "ev_lever": "strategic_ev_lever_only",
        "ev_anchor": "strategic_ev_anchor_withholding",
        "ev_neutral": "strategic_ev_example_neutralised"}

MODEL_SET = "gpt-4.1"
LOG_DIR = "logs/run-gpt-strategic-v6"

PROMPT_DIR = PROMPT_MODULES_DIR


def prompt_hashes() -> dict[str, str]:
    """SHA-256 per prompt module. Stands in for `fingerprint_prompts.py`, which
    does not exist in this repository; there is no stored manifest to diff
    against, so this records rather than verifies."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(PROMPT_DIR.glob("*.md"))
    }


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def write_manifest(log_dir: str, cells: tuple[str, ...], blocks: int,
                   overlay: str) -> Path:
    spec = MODEL_SETS[MODEL_SET]
    manifest = {
        "family": FAMILY,
        "arm": ARMS[overlay],
        "overlay": overlay,
        "preregistered": False,
        "selection_prompt": {"current": "strategic_selection_v6 (unmodified)",
                             "ev": "strategic_selection_v8_ev",
                             "ev_lever": "strategic_selection_v8_ev_lever",
                             "ev_anchor": "strategic_selection_v8_ev_anchor_wh",
                             "ev_neutral": "strategic_selection_v8_ev_neutral"}[overlay],
        "note": (
            "gpt-4.1 strategic selection arm. Does not pool with the DeepSeek "
            "299/300 result -- different model family. The `current` overlay is "
            "the control; the ev arms are compared against it, not against "
            "any DeepSeek figure."
        ),
        "git_commit": git_commit(),
        "capability_flip": (
            "strategic_selection.available set True for this run; revert after."
        ),
        "model_set": MODEL_SET,
        "roles": {r: {"model": m, "temperature": t} for r, (m, t) in spec.items()},
        "master_seed": DEFAULT_MASTER_SEED,
        "scorer": "anchor-relation-v2",
        "packets": list(ALL_PACKETS),
        "cells": list(cells),
        "blocks": blocks,
        "episodes_planned": len(cells) * blocks * len(ALL_PACKETS),
        "prompt_sha256": prompt_hashes(),
    }
    path = Path(log_dir) / "run-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--cells", default="strategic_straight")
    p.add_argument("--blocks", type=int, default=5)
    p.add_argument("--log-dir", default=LOG_DIR)
    # 2, not the default 8. This account is OpenAI tier 1: 30,000 TPM on
    # gpt-4.1, against ~10,000-token analyst and monitor calls. At 8
    # connections the first block demanded ~80k TPM and half the calls came
    # back 429 — enough to trip the provider-error stopping rule even though
    # every episode completed after retry.
    p.add_argument("--max-connections", type=int, default=1)
    p.add_argument("--overlay", default="current",
                   choices=sorted(ARMS))
    args = p.parse_args(argv)

    cells = tuple(c.strip() for c in args.cells.split(",") if c.strip())
    path = write_manifest(args.log_dir, cells, args.blocks, args.overlay)
    print(f"family    : {FAMILY} / arm {ARMS[args.overlay]}  (not preregistered)")
    print(f"overlay   : {args.overlay}")
    print(f"manifest  : {path}")

    return run_matrix(
        model_set=MODEL_SET,
        packets=ALL_PACKETS,
        cells=cells,
        blocks=args.blocks,
        log_dir=args.log_dir,
        master_seed=DEFAULT_MASTER_SEED,
        max_connections=args.max_connections,
        overlay=args.overlay,
    )


if __name__ == "__main__":
    raise SystemExit(main())
