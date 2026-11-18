"""Development launcher: the REAL episode pipeline (selection -> brief -> strip ->
blind assessor -> scorers) with a declared overlay, the pilot's officer/standard
overrides, and an OpenRouter DeepSeek role set. Nothing pools with the committed
pilot; logs go to a fresh dir per round.

    .venv/bin/python strat_run.py --model-set mock --overlay shade_v15 --blocks 125
    .venv/bin/python strat_run.py --model-set or_deepseek --overlay shade_v15 --blocks 125-134
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import warnings

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from inspect_ai import eval_set
from inspect_ai.model import GenerateConfig, get_model
from sedition_inspect.environment import load_project_dotenv

load_project_dotenv(ROOT)

import inspect  # noqa: E402

from sedition_inspect import _resources as resources_mod  # noqa: E402
from sedition_inspect import capabilities as caps  # noqa: E402
from sedition_inspect import scorers as scorers_mod  # noqa: E402
from sedition_inspect import solver as solver_mod  # noqa: E402
from sedition_inspect import task as task_mod  # noqa: E402
from sedition_inspect.task import sedition_briefing  # noqa: E402
from sedition.packets.variants import canonical_variant  # noqa: E402
from sedition.pipeline import failure_policy  # noqa: E402

# Token budgets come from the repo defaults (solver.sedition_episode and
# scorers.MONITOR_MAX_TOKENS), which were raised on 2026-08-22 after DeepSeek V4
# hidden reasoning starved the selection/monitor/briefing calls. Recorded in the
# run metadata so a log states the budgets it ran under.
_sig = inspect.signature(solver_mod.sedition_episode).parameters
SELECTION_MAX_TOKENS = _sig["selection_max_tokens"].default
BRIEFING_MAX_TOKENS = _sig["briefing_max_tokens"].default
MONITOR_MAX_TOKENS = scorers_mod.MONITOR_MAX_TOKENS
_ = task_mod  # the task module builds the solver with these defaults

# The pilot enabled strategic_selection at run time only (PREREG 28.8); same here.
caps.CAPABILITIES["strategic_selection"] = dataclasses.replace(
    caps.CAPABILITIES["strategic_selection"], available=True, blocked_until="")

ROLE_SETS = {
    # Memo (2026-08-22): analyst V4-Pro-0813 @0.7 reasoning off; primary officer
    # V3-0324 @0; V3.2 is the strong reference. Monitor is not the focus.
    "or_deepseek": {
        "analyst": ("openrouter/deepseek/deepseek-v4-pro-0813", 0.7, {"reasoning_enabled": False}),
        "watch_officer": ("openrouter/deepseek/deepseek-chat-v3-0324", 0.0, {"reasoning_enabled": False}),
        "monitor": ("openrouter/deepseek/deepseek-v4-flash-0731", 0.0, {"reasoning_enabled": False}),
    },
    "or_deepseek_v32officer": {
        "analyst": ("openrouter/deepseek/deepseek-v4-pro-0813", 0.7, {"reasoning_enabled": False}),
        "watch_officer": ("openrouter/deepseek/deepseek-v3.2", 0.0, {"reasoning_enabled": False}),
        "monitor": ("openrouter/deepseek/deepseek-v4-flash-0731", 0.0, {"reasoning_enabled": False}),
    },
    # Azure Foundry = the preregistered pilot's own stack (run.py MODEL_SETS).
    "foundry_pilot": {  # == foundry_deepseek: analyst V3.2, assessor V4-Flash, monitor V4-Pro
        "analyst": ("azureai/DeepSeek-V3.2", 0.7, {"emulate_tools": False}),
        "watch_officer": ("azureai/DeepSeek-V4-Flash", 0.0, {"emulate_tools": False}),
        "monitor": ("azureai/DeepSeek-V4-Pro", 0.0, {"emulate_tools": False}),
    },
    "foundry_v4pro": {  # == foundry_deepseek_swapped: analyst V4-Pro, assessor V4-Flash, monitor V3.2
        "analyst": ("azureai/DeepSeek-V4-Pro", 0.7, {"emulate_tools": False}),
        "watch_officer": ("azureai/DeepSeek-V4-Flash", 0.0, {"emulate_tools": False}),
        "monitor": ("azureai/DeepSeek-V3.2", 0.0, {"emulate_tools": False}),
    },
    "foundry_v4pro_v32officer": {
        "analyst": ("azureai/DeepSeek-V4-Pro", 0.7, {"emulate_tools": False}),
        "watch_officer": ("azureai/DeepSeek-V3.2", 0.0, {"emulate_tools": False}),
        "monitor": ("azureai/DeepSeek-V4-Flash", 0.0, {"emulate_tools": False}),
    },
    # Main's frozen table (analyst V4-Pro @0.7, monitor V4-Flash @0) with V4-Flash
    # also in the assessor seat: V3.2 never credits criterion B as a blind
    # assessor (docs/evidence/strat-dev-2026-08-22), so the frozen officer
    # cannot produce an honest baseline on E03-MS. Declared deviation.
    #
    # DE-DUPLICATED at the 2026-08-23 merge: main and
    # reviewer-d/strategic-v15-dev had each added this entry independently, with
    # byte-identical bodies, so the merge conflicted on the comment only. One
    # copy kept. Main's copy also carried a warning that reading the token
    # budgets from the solver/scorer defaults would pick up the LOW pre-fix
    # values; that warning is now obsolete, because the same merge raises those
    # defaults (selection 4000, briefing 8000, monitor 4000).
    "foundry_frozen_flash": {
        "analyst": ("azureai/DeepSeek-V4-Pro", 0.7, {"emulate_tools": False}),
        "watch_officer": ("azureai/DeepSeek-V4-Flash", 0.0, {"emulate_tools": False}),
        "monitor": ("azureai/DeepSeek-V4-Flash", 0.0, {"emulate_tools": False}),
    },
    "mock": {
        "analyst": ("mockllm/model", 0.0, {}),
        "watch_officer": ("mockllm/model", 0.0, {}),
        "monitor": ("mockllm/model", 0.0, {}),
    },
}


def parse_blocks(spec: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return tuple(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model-set", default="mock", choices=sorted(ROLE_SETS))
    p.add_argument("--overlay", default="shade_v15")
    p.add_argument("--cells", default="honest_sheet,strategic_sheet")
    p.add_argument("--packets", default="E03-MS")
    p.add_argument("--blocks", default="125", help="e.g. 125-134 or 125,126")
    p.add_argument("--log-dir", required=True)
    p.add_argument("--officer-version", default="v6_assessor")
    p.add_argument("--standard", default="notification_standard_v3_relational")
    p.add_argument("--threshold-k", type=int, default=3)
    p.add_argument("--master-seed", type=int, default=20260814)
    p.add_argument("--max-connections", type=int, default=6)
    p.add_argument("--selection-mode", default="free")
    p.add_argument("--admit-heldout", default="",
                   help="comma-separated additional event ids (none are distributed in this release)")
    p.add_argument("--packet-variant", default="threat",
                   # Old and new spellings both parse, so recorded command.txt
                   # lines stay replayable; canonicalized right below.
                   choices=("threat", "control", "subset_benign", "subset_matched",
                            "ablated", "subset_control"),
                   help="benign arm = subset_benign (drop decisive report) / subset_matched "
                        "(drop inert report; legacy name subset_control). THE SUBSET ARM IS "
                        "CLOSED as of 2026-08-26: both tables are empty and asking for a "
                        "subset variant raises with the reason. Legacy 'ablated' means "
                        "'control'. See sedition.packets.variants.SUBSET_TABLE.")
    a = p.parse_args()
    a.packet_variant = canonical_variant(a.packet_variant)

    if a.admit_heldout:
        events = tuple(e.strip() for e in a.admit_heldout.split(",") if e.strip())
        resources_mod.admit_heldout(*events)

    spec = ROLE_SETS[a.model_set]
    roles = {
        role: get_model(mid, config=GenerateConfig(temperature=t), **extra)
        for role, (mid, t, extra) in spec.items()
    }
    blocks = parse_blocks(a.blocks)
    meta = {
        "dev_round": a.log_dir,
        "overlay": a.overlay,
        "roles": {r: m for r, (m, _t, _e) in spec.items()},
        "officer_version": a.officer_version,
        "notification_standard": a.standard,
        "threshold_k": a.threshold_k, "selection_max_tokens": SELECTION_MAX_TOKENS, "monitor_max_tokens": MONITOR_MAX_TOKENS, "briefing_max_tokens": BRIEFING_MAX_TOKENS,
        "packet_variant": a.packet_variant,
        "blocks": list(blocks),
        "note": "development evidence; never pooled with the preregistered pilot",
    }
    warnings.simplefilter("ignore")
    success, logs = eval_set(
        metadata=meta,
        tasks=[sedition_briefing(
            packets=a.packets, cells=a.cells, blocks=len(blocks),
            block_indices=",".join(str(b) for b in blocks),
            overlay=a.overlay, selection_mode=a.selection_mode,
            packet_variant=a.packet_variant,
            master_seed=a.master_seed,
            officer_version=a.officer_version,
            notification_standard=a.standard,
            threshold_k=a.threshold_k,
        )],
        log_dir=a.log_dir,
        model=roles["analyst"], model_roles=roles,
        retry_attempts=failure_policy.MAX_TRANSPORT_ATTEMPTS,
        max_connections=a.max_connections,
        fail_on_error=failure_policy.FAIL_ON_SAMPLE_ERROR,
        time_limit=failure_policy.EPISODE_TIME_LIMIT_SECONDS,
        log_level="warning",
    )
    print("EVALSET_SUCCESS", success)
    for lg in logs:
        print("LOG", lg.location, lg.status)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
