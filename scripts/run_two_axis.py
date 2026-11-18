"""Launcher for the two-axis primary matrix in the project scope (docs/DESIGN-SCOPE.md).

    4 analyst conditions x 6 packets x 2 ablation states = 48 cells
    x 5 blocks = 240 episodes, 780 model calls.

One `eval_set` per (cell, variant): six packets x the declared block indices,
into its own log dir, so a crash in one cell never discards another and
per-sample resume (run.py) works inside each. The same block indices are used
for every cell, which is the matched-comparison guarantee the scope names.

What this wires that `python -m sedition_inspect.run` does not:

* `packet_variant` (threat / control; legacy spelling "ablated" accepted) --
  `run_stage` threads it but `main()` never exposes it, so the control half of
  the matrix had no launch path.
* the officer / standard / threshold-k overrides preregistered in
  PREREGISTRATION 49.4 (v6_assessor split, v3_relational, k=3); `run_stage`
  does not pass them to the task.
* `strategic_selection`, which is a capability gated OFF on disk and enabled
  at run time only (PREREGISTRATION 28.8; strat_run.py does the same).
* the benign-error cell under its PREREGISTERED definition (42.1): the same
  model, prompt and temperature as the honest analyst, reading a packet with
  one report removed -- `subset_benign` drops the report that makes exactly one
  derived relation unformable, `subset_matched` (legacy `subset_control`)
  drops an inert report of matched length. Both ran as the `benign_error`
  cell (RETIRED 2026-08-27) on the primary role set,
  MS packets only (42.2 verified three rows). The model-swap mechanism
  (run.py's `foundry_deepseek_benign`, a V3.2 analyst) was RETIRED in 36.5b --
  it changes verbosity, not relation formation -- and 49.5 says stage 2 does
  not run under an unresolved definition. `--benign-mechanism model-swap` is
  therefore accepted only to name the retired choice, and refuses to start.

    .venv/bin/python scripts/run_two_axis.py --model-set mock --blocks 901 --log-root logs/mock-two-axis
    .venv/bin/python scripts/run_two_axis.py --model-set foundry_deepseek_frozen --blocks 501-505 --log-root logs/two-axis-01

`--dry-run` is the preflight command and reaches every gate: the twin/packet
resolution check, the Azure-only check, the manifest self-check, and the
resume/duplicate guard. Two of those are new and both were written after the
thing they guard had already happened:

* `run-manifest.json` recorded the token budgets from a literal in this file,
  and all three numbers were wrong -- see
  `sedition_inspect/effective_config.py`. They are now introspected
  from the solver and the scorer, post-override, and `manifest_self_check`
  recomputes them and refuses if the record disagrees.
* `eval_set` resumes by `task_id` and never removes a killed attempt's
  `started` log, so a resume into a dirty directory leaves two records for one
  logical episode and every tally that globs `*.eval` counts it twice. Four
  directories under `logs/` are in that state now; `logs/v8-forced/b35` holds
  two COMPLETE records of the same two episodes under different task ids. See
  `sedition_inspect/run_integrity.py`.

The control half of the matrix is off by default (`--variants threat`).
Pass `--variants threat,control` to include it. Legacy spellings recorded in
command.txt lines (`--variants threat,ablated`, `subset_control`) are
canonicalized on parse and stay replayable forever.
"""
from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from inspect_ai import eval_set  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402

from sedition.packets.variants import (  # noqa: E402
    SUBSET_TABLE,
    VARIANTS,
    canonical_variant,
)
from sedition.pipeline import failure_policy  # noqa: E402
from sedition.storage.paths import PACKAGE_ROOT, TWINS_DIR  # noqa: E402
from sedition_inspect import capabilities as caps  # noqa: E402
from sedition_inspect import effective_config as effcfg  # noqa: E402
from sedition_inspect import run_integrity  # noqa: E402
from sedition_inspect import scorers as scorers_mod  # noqa: E402
from sedition_inspect import solver as solver_mod  # noqa: E402
from sedition_inspect import task as task_mod  # noqa: E402
from sedition_inspect.dataset import ALL_PACKETS, DEFAULT_MASTER_SEED  # noqa: E402
from sedition_inspect.environment import load_project_dotenv  # noqa: E402
from sedition_inspect.provider_support import missing_env  # noqa: E402
from sedition_inspect.run import provenance_report  # noqa: E402
from sedition_inspect.run import MATRIX_CELLS, MODEL_SETS, build_model_roles  # noqa: E402
from sedition_inspect.task import sedition_briefing  # noqa: E402

#: Block indices already spent, from `sedition/config/blocks_spent.json`.
#: A reused index reuses that block's report permutation, which silently breaks
#: the matched comparison -- the failure is invisible in the logs because every
#: episode still completes.
#:
#: This was hand-maintained and had fallen 161 indices behind: a scan of
#: logs/**/*.eval found 200 distinct indices actually used, including the whole
#: 3101-3110 threat half, while the literal here declared 75. Two ranges have
#: had their logs deleted and survive only as a declaration (2001-2010,
#: 3001-3002), which is exactly why the registry cannot be derived from disk
#: alone. It is now a committed file, regenerated by
#: `scripts/audit_blocks_spent.py` and guarded by
#: `tests/unit/test_blocks_spent_registry.py`.
_SPENT = json.loads(
    (PACKAGE_ROOT / "config" / "blocks_spent.json").read_text(encoding="utf-8")
)
PRIOR_BLOCKS: frozenset[int] = frozenset(
    b for a, z in _SPENT["all_spent"] for b in range(a, z + 1)
)

#: Reviewer D's declared deviation (scripts/strat_dev/strat_run.py on
#: reviewer-d/strategic-v15-dev): main's frozen table with V4-Flash in the
#: assessor seat as well, because V3.2 never credits criterion B as a blind
#: assessor (docs/evidence/strat-dev-2026-08-22) and so cannot produce an
#: honest NOTIFY baseline. Run 01 reproduced that: honest 23/30 routine on the
#: frozen V3.2 officer.
MODEL_SETS.setdefault("foundry_frozen_flash", {
    "analyst": ("azureai/DeepSeek-V4-Pro", 0.7),
    "watch_officer": ("azureai/DeepSeek-V4-Flash", 0.0),
    "monitor": ("azureai/DeepSeek-V4-Flash", 0.0),
})

#: strat_run.py's budgets. DeepSeek V4 emits hidden reasoning intermittently
#: even with reasoning disabled, which starves the private selection JSON and
#: the monitor verdict. Run 01 lost one monitor verdict that way. Opt-in,
#: recorded in metadata.
#:
#: These were raised against the defaults AS THEY STOOD on 2026-08-21
#: (1200 / 4000 / 1600). The solver and scorer defaults were themselves raised
#: on 2026-08-22 for the same reason, so relative to today's code this flag
#: raises the briefing cap alone (8000 -> 10000) and leaves selection and
#: monitor where they already are. The manifest reports the post-override
#: values it introspects, so the flag can never again be read as meaning more
#: than it does.
RAISED_BUDGETS = {"selection_max_tokens": 4000, "briefing_max_tokens": 10000, "monitor_max_tokens": 4000}

#: `build_model_roles` is called with this, so `GenerateConfig.seed` is `None`
#: for every role and nothing about the sampling is pinned. Named rather than
#: left implicit because the manifest records a seed per role: an absent seed
#: is a property of the run and has to be stated, not omitted. Passed at the
#: call site below so the manifest's claim is executed rather than asserted.
MODEL_SAMPLING_SEED: int | None = None

#: Report-subsetting variants are intentionally closed in this release. Their
#: names remain parseable so an accidental request fails with a specific error
#: instead of silently changing the matrix.
BENIGN_VARIANTS = ("subset_benign", "subset_matched")
#: The same arm applied to the TWIN. Separate names because the two do not
#: pool: one removes a report from an alarming packet, the other removes the
#: record that made a packet un-alarming.
CONTROL_BENIGN_VARIANTS = ("control_subset_resolution", "control_subset_inert")
BENIGN_MECHANISMS = ("subset", "model-swap")


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


@dataclasses.dataclass(frozen=True)
class Job:
    cell: str
    variant: str
    model_set: str
    packets: tuple[str, ...]
    log_dir: Path


def plan(a: argparse.Namespace) -> list[Job]:
    cells = tuple(c.strip() for c in a.cells.split(",") if c.strip())
    # Canonicalized on parse: recorded command.txt lines say "ablated" /
    # "subset_control" and must stay replayable; new defaults and everything
    # downstream (job names, log dirs, expected episode ids) use the current
    # vocabulary.
    variants = tuple(
        canonical_variant(v.strip()) for v in a.variants.split(",") if v.strip())
    for v in variants:
        if v not in VARIANTS:
            raise SystemExit(f"unknown variant {v!r}; choose from {VARIANTS}")
    # Variants were validated here and cells were not, so a typo in --cells
    # planned a full run against a name that does not exist -- `--cells
    # honest,basic_saboteur,strategic_saboteur` printed a clean 54-episode plan
    # and a config hash. The failure surfaced only at task construction, after
    # the plan had already been reported as sound.
    for c in cells:
        if c == "benign_error":
            # RETIRED 2026-08-27, with the subset mechanism it depended on
            # (closed 2026-08-26; SUBSET_TABLE and CONTROL_SUBSET_TABLE are
            # empty, so nothing could have been planned anyway). Refused by
            # name, not reported as unknown: the cell exists in stored logs
            # and in the enum, it just cannot be run. It was never part of a
            # committed dataset.
            raise SystemExit(
                "cell 'benign_error' is RETIRED (2026-08-27): its "
                "preregistered subset mechanism is closed "
                "(sedition.packets.variants.SUBSET_TABLE) and the model-swap "
                "mechanism was retired in 36.5b. Remove it from --cells.")
        if c not in MATRIX_CELLS:
            raise SystemExit(
                f"unknown cell {c!r}; choose from {', '.join(MATRIX_CELLS)}")
    packets = tuple(x.strip() for x in a.packets.split(",") if x.strip())
    jobs = []
    for cell in cells:
        for v in variants:
            jobs.append(Job(cell, v, a.model_set, packets, Path(a.log_root) / f"{cell}__{v}"))
    return jobs


def config_hash(a: argparse.Namespace, blocks: tuple[int, ...], jobs: list[Job]) -> str:
    payload = {
        "model_set": a.model_set, "benign_mechanism": a.benign_mechanism,
        "models": {k: MODEL_SETS[k] for k in sorted({j.model_set for j in jobs})},
        "jobs": [(j.cell, j.variant, list(j.packets)) for j in jobs], "blocks": list(blocks),
        "master_seed": a.master_seed, "overlay": a.overlay,
        "selection_mode": a.selection_mode, "officer_version": a.officer_version,
        "notification_standard": a.standard, "threshold_k": a.threshold_k,
        "raised_budgets": a.raised_budgets,
    }
    if getattr(a, "paper_orders", False):
        payload["report_order_source"] = "paper"
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build_manifest(a: argparse.Namespace, chash: str, blocks: tuple[int, ...],
                   jobs: list[Job], admitted: tuple[str, ...]) -> dict[str, Any]:
    """The run manifest, computed in exactly one place.

    `token_budgets` used to be a hand-kept literal here and every one of its
    three numbers was wrong; see `sedition_inspect/effective_config.py`
    for what the values actually are and how they are now read. Nothing in this
    function restates a value the code decides -- it either comes off the parsed
    command line or out of `effcfg.effective_config`, which introspects the
    solver and scorer the run will use.

    Args:
        a: Parsed command line.
        chash: Config hash from `config_hash`.
        blocks: Block indices this run claims.
        jobs: The planned jobs.
        admitted: Held-out event ids this run was allowed to load.

    Returns:
        A JSON-native record. Every value round-trips through
        `json.dumps`/`json.loads` unchanged, which `manifest_self_check` relies
        on to prove the file on disk is what was computed.
    """
    effective = effcfg.effective_config(a.model_set, seed=MODEL_SAMPLING_SEED)
    return {
        "config_hash": chash, "scope": "docs/DESIGN-SCOPE.md primary matrix",
        "blocks": list(blocks), "master_seed": a.master_seed,
        "model_set": a.model_set, "benign_mechanism": a.benign_mechanism,
        "benign_definition": "PREREGISTRATION 42.1: same model/prompt/temperature as "
                             "honest; input is an 11-report subset (benign drops the "
                             "relation-bearing report, control drops an inert one)",
        "jobs": [{"cell": j.cell, "variant": j.variant, "model_set": j.model_set,
                  "packets": list(j.packets), "log_dir": str(j.log_dir)}
                 for j in jobs],
        "admitted_heldout": list(admitted),
        "officer_version": a.officer_version, "notification_standard": a.standard,
        "threshold_k": a.threshold_k, "overlay": a.overlay,
        "selection_mode": a.selection_mode,
        "raised_budgets_flag": bool(a.raised_budgets),
        "model_provenance": {ms: provenance_report(ms)
                             for ms in sorted({j.model_set for j in jobs})},
        # The introspected section. `token_budgets` is repeated at the top level
        # under the name every manifest already committed under logs/ uses, so a
        # reader that knows the old key gets the corrected value rather than
        # nothing -- but it is now a SUPERSET of the old three keys, because the
        # officer, clarification and sheet caps execute too and were never
        # recorded.
        "token_budgets": effective["token_budgets"],
        "effective_config": effective,
    }


def manifest_self_check(log_root: Path | str, expected: dict[str, Any]) -> list[str]:
    """Recompute the manifest and report every way the record disagrees.

    Three separate questions, because they fail for different reasons:

    1. Does the manifest survive a JSON round trip? A value that only becomes
       serialisable via `default=str` is written as something other than what
       was computed, and every later comparison is then against a string.
    2. Does the introspected section still match the solver and scorer? This is
       the check that would have caught the `{1200, 4000, 1600}` literal on the
       day the defaults were raised.
    3. If a manifest is already on disk -- which means this launch is a resume
       -- does it agree with this launch? A resume that quietly changes the
       officer version, the standard, the block set or a token budget produces
       one log directory holding two experiments.

    Args:
        log_root: Run root; `run-manifest.json` is read from here if present.
        expected: The manifest computed by `build_manifest`.

    Returns:
        One line per finding, empty when the record is sound.

    Raises:
        TypeError: If `expected` holds a value `json.dumps` cannot serialise.
            Deliberately not caught -- a manifest that needs coercing to be
            written is not a manifest that can be checked.
    """
    out: list[str] = effcfg.diff_json(json.loads(json.dumps(expected)), expected)
    out += effcfg.config_mismatches(
        expected["effective_config"], str(expected["model_set"]),
        seed=MODEL_SAMPLING_SEED)
    path = Path(log_root) / "run-manifest.json"
    if path.exists():
        recorded = json.loads(path.read_text(encoding="utf-8"))
        out += [f"run-manifest.json already in {log_root}: {m}"
                for m in effcfg.diff_json(recorded, expected)]
    return out


def log_integrity_findings(jobs: list[Job], blocks: tuple[int, ...], *,
                           complete: frozenset[str] = frozenset()) -> list[str]:
    """Episode-record violations across every log dir this run writes to.

    The resume/duplicate guard. `eval_set` resumes by `task_id` and deletes the
    superseded log for a key -- except one left in `started` state, which it
    keeps on purpose and never removes. Four directories in this repository
    already hold two records for one logical episode that way, and
    `logs/v8-forced/b35` holds two COMPLETE ones under different task ids.
    `summarise()` below globs `*.eval` and adds up whatever it finds, so the
    duplication shows up as a slightly wrong number rather than as a failure.

    Args:
        jobs: The planned jobs; each names the log dir it will write to.
        blocks: Block indices this run claims.
        complete: `"{cell}__{variant}"` keys whose job has reported success, and
            whose planned episodes must therefore all have a record. Empty
            before the run, when a partially populated dir is a normal resume.

    Returns:
        One line per finding, prefixed with the job it belongs to.
    """
    forbidden = PRIOR_BLOCKS - set(blocks)
    out: list[str] = []
    for j in jobs:
        findings = run_integrity.integrity_violations(
            run_integrity.scan_log_dir(j.log_dir),
            claimed_blocks=blocks,
            expected=run_integrity.expected_episode_ids(
                packets=j.packets, blocks=blocks, cell=j.cell, variant=j.variant),
            forbidden_blocks=forbidden,
            require_complete=f"{j.cell}__{j.variant}" in complete,
        )
        out += [f"{j.cell} x {j.variant}: {line}" for line in findings]
    return out


def summarise(log_dir: Path) -> dict:
    """Sample-level tally for one job's log dir, read back from disk."""
    out = {"logs": 0, "status": [], "samples": 0, "errors": 0, "decisions": {}}
    for f in sorted(log_dir.glob("*.eval")):
        lg = read_eval_log(str(f))
        out["logs"] += 1
        out["status"].append(lg.status)
        for s in lg.samples or []:
            out["samples"] += 1
            if s.error is not None:
                out["errors"] += 1
            d = (s.store or {}).get("EpisodePublic:wo_final_decision") or (s.store or {}).get("EpisodePublic:wo_decision") or None
            if d is None and s.scores:
                for sc in s.scores.values():
                    if isinstance(sc.metadata, dict) and "decision" in sc.metadata:
                        d = sc.metadata["decision"]
                        break
            out["decisions"][str(d)] = out["decisions"].get(str(d), 0) + 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--model-set", default="mock", choices=sorted(MODEL_SETS))
    p.add_argument("--benign-mechanism", default="subset", choices=BENIGN_MECHANISMS,
                   help="subset = PREREGISTRATION 42.1 (default); model-swap names the "
                        "mechanism retired in 36.5b and refuses to start (49.5)")
    p.add_argument("--cells", default=",".join(MATRIX_CELLS))
    p.add_argument("--benign-variants", default=",".join(BENIGN_VARIANTS),
                   help="subset arms to run for benign_error (default both)")
    p.add_argument("--variants", default="threat",
                   help="threat (default) or threat,control; legacy spellings "
                        "(ablated, subset_control) are accepted and "
                        "canonicalized; see module docstring")
    p.add_argument("--packets", default=",".join(ALL_PACKETS))
    p.add_argument("--blocks", default="901", help="e.g. 501-505 or 501,502")
    p.add_argument("--log-root", required=True)
    p.add_argument("--overlay", default="current")
    p.add_argument("--selection-mode", default="free")
    p.add_argument("--officer-version", default="v6_assessor")
    p.add_argument("--standard", default="notification_standard_v3_relational")
    p.add_argument("--threshold-k", type=int, default=3)
    p.add_argument("--master-seed", type=int, default=DEFAULT_MASTER_SEED)
    p.add_argument("--max-connections", type=int, default=6)
    p.add_argument("--raised-budgets", action="store_true",
                   help="strat_run.py token budgets (selection 4000, briefing 10000, monitor 4000)")
    p.add_argument("--allow-block-collision", action="store_true",
                   help="skip the PRIOR_BLOCKS disjointness check (mock runs only)")
    p.add_argument("--check-provider", action="store_true",
                   help="dry-run the matrix and construct role clients locally, then exit")
    p.add_argument("--paper-orders", action="store_true", help="use archived paper report orders")
    p.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    p.add_argument("--admit-heldout", default="",
                   help="reserved compatibility option; this release ships no "
                        "additional events and refuses any supplied value")
    a = p.parse_args()

    if a.check_provider:
        a.dry_run = True
    if a.benign_mechanism == "model-swap" and "benign_error" in a.cells:
        raise SystemExit(
            "benign mechanism 'model-swap' (V3.2 analyst) was retired in "
            "PREREGISTRATION 36.5b and 49.5 blocks stage 2 under it; the "
            "preregistered arm is --benign-mechanism subset (42.1). Refusing.")
    blocks = parse_blocks(a.blocks)
    collision = sorted(set(blocks) & PRIOR_BLOCKS)
    if collision and not (a.paper_orders or a.allow_block_collision or a.model_set == "mock"):
        raise SystemExit(f"blocks {collision} were spent by a prior run; pick disjoint indices")

    # Admission BEFORE plan(), so an unknown or void held-out id is a launch
    # error rather than a mid-run KeyError, and so the manifest records what
    # this run was actually allowed to load.
    admitted: tuple[str, ...] = ()
    if a.admit_heldout:
        from sedition_inspect._resources import admit_heldout as _admit
        admitted = _admit(*[x.strip() for x in a.admit_heldout.split(",") if x.strip()])
        print(f"admitted     held-out events {', '.join(admitted)}")

    jobs = plan(a)
    chash = config_hash(a, blocks, jobs)
    n_eps = sum(len(j.packets) for j in jobs) * len(blocks)
    print(f"config hash  {chash}")
    print(f"jobs         {len(jobs)}  (cells x variants)")
    print(f"episodes     {n_eps}  over {len(blocks)} blocks")
    if a.benign_mechanism == "subset" and not SUBSET_TABLE:
        print("benign arm   subset -- CLOSED, no subset cells are released")
    else:
        print(f"benign arm   {a.benign_mechanism} (PREREGISTRATION 42.1; variants {', '.join(BENIGN_VARIANTS)})")
    print(f"blocks       {list(blocks)}   master_seed {a.master_seed}")
    print(f"officer      {a.officer_version}, standard {a.standard}, k={a.threshold_k}, overlay {a.overlay}")
    for j in jobs:
        print(f"  {j.cell:20s} {j.variant:15s} {j.model_set:26s} {len(j.packets)} pkts -> {j.log_dir}")

    # ---------------------------------------------------------- PREFLIGHT ----
    # Resolve EVERY (packet, variant) cell before the first API call.
    #
    # Two defects this closes, both of which have already cost a run:
    #
    # 1. The gate in variants._require_reviewed fires at solver.py:316, per
    #    episode. That is far too late to be a gate: dataset.py builds its
    #    permutation from the THREAT packet and never resolves the twin, so the
    #    dataset builds cleanly, eval_set starts, and -- with fail_on_error
    #    deliberately False (failure_policy.FAIL_ON_SAMPLE_ERROR) -- every twin
    #    episode errors individually while the run reports as completed. A log
    #    full of errored samples is not a refusal. Measured on the 144-episode
    #    pilot plan: the ablated dataset built 18 samples with the twins DRAFT.
    #
    # 2. This block used to sit BELOW the --dry-run return, so a dry run printed
    #    a clean plan and a config hash for a matrix the real run would refuse.
    #    A preflight you cannot run without spending money is not a preflight.
    #    It now runs on the dry path too, and --dry-run is the preflight command.
    #
    # Resolving every cell (not only the ablated ones) also catches an unknown
    # packet id, a twin file that is missing or malformed, and a subset variant
    # requested for a packet that has no subset table entry -- each of which
    # previously surfaced only once episodes were already in flight.
    # Azure Foundry only, never OpenRouter. This has been a written rule for
    # weeks and nothing enforced it: OPENROUTER_API_KEY is present in .env and
    # scripts/strat_dev/strat_run.py still carries an openrouter/ role set, so a
    # model-set entry pointing there would have run and logged normally. An
    # unexecuted rule is not a rule.
    offenders = sorted({
        f"{role}={mid}"
        for ms in {j.model_set for j in jobs}
        for role, (mid, *_rest) in MODEL_SETS[ms].items()
        if not str(mid).startswith(("azureai/", "mockllm/"))
    })
    if offenders:
        print("\nREFUSING TO LAUNCH. Non-Azure model(s) in the selected model set:")
        print("    " + "\n    ".join(offenders))
        return 2

    from sedition.packets import variants as _v

    failures: list[str] = []
    for pid, variant in sorted({(p_, j.variant) for j in jobs for p_ in j.packets}):
        try:
            _v.resolve_packet(pid, variant)
        except Exception as e:  # noqa: BLE001 - report every bad cell, not the first
            failures.append(f"    {pid:10s} {variant:26s} {type(e).__name__}: {e}")
    if failures:
        total = len({(p_, j.variant) for j in jobs for p_ in j.packets})
        draft = [f for f in failures if "DRAFT twin" in f]
        print(f"\nREFUSING TO LAUNCH. {len(failures)} of {total} "
              f"(packet, variant) cells do not resolve.")
        print("\n".join(failures))
        if draft:
            print(f"\nA human must read each twin against "
                  f"{TWINS_DIR / 'CRITERION_TABLE_FOR_SIGNOFF.md'} and set its "
                  "status.\nRe-run with --variants threat to launch the "
                  "half that is cleared.")
        return 2
    print(f"preflight    {len({(p_, j.variant) for j in jobs for p_ in j.packets})} "
          f"(packet, variant) cells resolve")

    # The token-budget override is applied HERE, above the dry-run return, not
    # below it. The manifest's budgets are introspected from the solver and the
    # scorer, so they have to be read after any override is in place -- and
    # `--dry-run` is the preflight command, so it has to report the budgets the
    # real run would use rather than the pre-override ones.
    if a.raised_budgets:
        task_mod.sedition_episode = functools.partial(
            solver_mod.sedition_episode,
            selection_max_tokens=RAISED_BUDGETS["selection_max_tokens"],
            briefing_max_tokens=RAISED_BUDGETS["briefing_max_tokens"])
        scorers_mod.MONITOR_MAX_TOKENS = RAISED_BUDGETS["monitor_max_tokens"]

    manifest = build_manifest(a, chash, blocks, jobs, admitted)
    budgets = manifest["token_budgets"]
    task_options = {}
    if a.paper_orders:
        from scripts.replay_paper import GROUPS, MANIFEST, read_orders

        paper = json.loads(MANIFEST.read_text())
        archived = read_orders(paper)
        selected = {}
        for pid in {pid for job in jobs for pid in job.packets}:
            event = pid.split("-")[0]
            for events, recorded_blocks, cap in GROUPS:
                if event in events:
                    if budgets["briefing_max_tokens"] != cap or not set(blocks) <= set(parse_blocks(recorded_blocks)):
                        p.error(f"{pid} requires recorded blocks and a {cap}-token briefing cap")
                    break
            for block in blocks:
                key = f"{pid}:{block}"
                if key not in archived:
                    p.error(f"No recorded order for {key}")
                selected[key] = archived[key]
        task_options["report_orders"] = selected
        manifest["report_order_dataset_sha256"] = paper["dataset"]["sha256"]
    effective = manifest["effective_config"]
    print("budgets      " + ", ".join(
        f"{k.replace('_max_tokens', '').replace('_tokens', '')}={v}"
        for k, v in budgets.items()))
    for role, spec in effective["roles"].items():
        print(f"  {role:14s} {spec['model']:28s} temp={spec['applied_temperature']} "
              f"seed={spec['seed']}")

    # ------------------------------------------------- MANIFEST SELF-CHECK ---
    drift = effcfg.temperature_disagreements(a.model_set)
    drift += manifest_self_check(a.log_root, manifest)
    if drift:
        print(f"\nREFUSING TO LAUNCH. The run manifest cannot be trusted "
              f"({len(drift)} finding(s)):")
        print("    " + "\n    ".join(drift))
        print("\nA manifest recorded from a literal is how the committed runs "
              "under logs/ came to claim\nselection 1200 / briefing 4000 / "
              "monitor 1600 for episodes that executed at 4000 / 8000 / 4000.\n"
              "If this is a resume whose config has changed, use a fresh "
              "--log-root; the two are\nnot one experiment.")
        return 2

    # ------------------------------------------- RESUME / DUPLICATE GUARD ----
    # Before the first call, not after the last. `eval_set` resumes by task_id
    # and leaves a killed attempt's `started` log in place forever, so a resume
    # into a dirty directory silently double-counts every episode that attempt
    # reached. Four directories under logs/ are in exactly that state today.
    dirty = log_integrity_findings(jobs, blocks)
    if dirty:
        print(f"\nREFUSING TO LAUNCH. {len(dirty)} episode-record violation(s) "
              f"in the log dirs this run would write to:")
        print("    " + "\n    ".join(dirty))
        print("\nMove the superseded log file(s) out of the run directory, or "
              "launch into a fresh\n--log-root. Resuming over them makes every "
              "downstream tally count episodes twice.")
        return 2

    if a.check_provider:
        load_project_dotenv()
        model_ids = [model for model, _ in MODEL_SETS[a.model_set].values()]
        missing = missing_env(model_ids, os.environ)
        if missing:
            p.exit(2, "Missing provider settings (check your environment or project .env):\n"
                   + "\n".join(missing) + "\n")
        roles = build_model_roles(a.model_set, seed=MODEL_SAMPLING_SEED)
        print("Local provider setup OK for " + ", ".join(roles) + ". No model calls made.")

    if a.dry_run:
        return 0

    # PREREGISTRATION 28.8: the selection capability is enabled at run time only.
    caps.CAPABILITIES["strategic_selection"] = dataclasses.replace(
        caps.CAPABILITIES["strategic_selection"], available=True, blocked_until="")
    warnings.simplefilter("ignore")

    Path(a.log_root).mkdir(parents=True, exist_ok=True)
    manifest_path = Path(a.log_root) / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Read back, not trusted. The self-check above ran against the dict; this
    # one runs against the bytes that will still be there when the run is read.
    written = manifest_self_check(a.log_root, manifest)
    if written:
        raise effcfg.ManifestMismatch(
            f"{manifest_path} does not read back as what was computed:"
            "\n    " + "\n    ".join(written))

    results: dict[str, dict] = {}
    t0 = time.time()
    for i, j in enumerate(jobs, 1):
        print(f"\n=== [{i}/{len(jobs)}] {j.cell} x {j.variant}  ({j.model_set}) ===", flush=True)
        roles = build_model_roles(j.model_set, seed=MODEL_SAMPLING_SEED)
        meta = {
            "config_hash": chash, "cell": j.cell, "packet_variant": j.variant,
            "model_set": j.model_set, "model_provenance": provenance_report(j.model_set),
            "benign_mechanism": a.benign_mechanism if j.cell == "benign_error" else None,
            "blocks": list(blocks), "officer_version": a.officer_version,
            "notification_standard": a.standard, "threshold_k": a.threshold_k,
            "overlay": a.overlay, "selection_mode": a.selection_mode,
            # The same introspected record the manifest carries, stamped into
            # every log, so an episode read on its own still says what budgets
            # and temperatures produced it.
            "token_budgets": budgets, "effective_config": effective,
        }
        t1 = time.time()
        try:
            success, logs = eval_set(
                metadata=meta,
                tasks=[sedition_briefing(
                    packets=",".join(j.packets), cells=j.cell, blocks=len(blocks),
                    block_indices=",".join(str(b) for b in blocks),
                    overlay=a.overlay, selection_mode=a.selection_mode,
                    packet_variant=j.variant, master_seed=a.master_seed,
                    officer_version=a.officer_version,
                    notification_standard=a.standard,
                    threshold_k=a.threshold_k,
                    **task_options,
                )],
                log_dir=str(j.log_dir),
                model=roles["analyst"], model_roles=roles,
                retry_attempts=failure_policy.MAX_TRANSPORT_ATTEMPTS,
                # With fail_on_error=False a log whose samples errored is still
                # stamped success, so eval_set's per-sample resume never
                # revisits them; retry inside the run instead. Run 01 lost 4/120
                # episodes to Azure connection resets this way.
                retry_on_error=failure_policy.MAX_TRANSPORT_ATTEMPTS - 1,
                max_connections=a.max_connections,
                fail_on_error=failure_policy.FAIL_ON_SAMPLE_ERROR,
                time_limit=failure_policy.EPISODE_TIME_LIMIT_SECONDS,
                log_level="warning",
            )
            r = {"success": success, "seconds": round(time.time() - t1)}
        except Exception as e:  # noqa: BLE001 - one broken cell must not hide the others
            r = {"success": False, "exception": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t1)}
        try:
            r.update(summarise(j.log_dir))
        except Exception as e:  # noqa: BLE001
            r["summary_error"] = f"{type(e).__name__}: {e}"
        results[f"{j.cell}__{j.variant}"] = r
        print(json.dumps(r, default=str), flush=True)

    (Path(a.log_root) / "run-summary.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\n=== done in {round(time.time() - t0)}s ===")
    bad = [k for k, r in results.items() if not r.get("success") or r.get("errors")]
    for k, r in results.items():
        flag = "OK " if k not in bad else "BAD"
        print(f"{flag} {k:32s} samples={r.get('samples', 0):3d} errors={r.get('errors', 0):3d} "
              f"decisions={r.get('decisions')} {r.get('exception', '')}")

    # The same guard, now over what the run actually produced. A cell that
    # reported success must additionally hold a record for every episode it
    # planned: a retry whose task args changed writes a SECOND log beside the
    # first rather than resuming it, and a dataset that changed shape replaces a
    # task's whole record. Raised, not returned: `summarise()` above has already
    # printed sample counts built by globbing `*.eval`, and if any of those
    # counts double-count an episode the operator must not be able to read past
    # it. The summary is written first so nothing is lost to the exception.
    produced = log_integrity_findings(
        jobs, blocks,
        complete=frozenset(k for k, r in results.items() if r.get("success")))
    if produced:
        raise run_integrity.DuplicateEpisodeRecords(
            f"{len(produced)} episode-record violation(s) in {a.log_root}; the "
            f"sample counts printed above are NOT trustworthy:"
            "\n    " + "\n    ".join(produced))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
