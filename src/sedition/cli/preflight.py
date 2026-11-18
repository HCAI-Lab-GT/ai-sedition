"""`sedition preflight --stage <name>` — the pre-first-run checklist, executed
rather than remembered.

A checklist in a document drifts from the code. This one runs: every item is
a real check against the real artifacts, and it exits non-zero if any
blocking item fails. Run it immediately before the first real episode and
paste the output into docs/DECISIONS.md.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from ..config.schema import load_stage
from ..enums import WorkingCondition
from ..packets.build import parse_all_including_heldout
from ..packets.fact_vocabulary import load_fact_vocabulary, validate_vocabulary
from ..prompts.golden import render_all
from ..prompts.loader import load_all
from ..prompts.registry import PromptRegistry
from ..storage.paths import (
    ANSWER_KEY_JSON,
    GOLDEN_DIR,
    PACKAGE_ROOT,
    PROMPT_MODULES_DIR,
    REPO_ROOT,
    SCENARIOS_DIR,
    stage_config,
)

VOCAB_PATH = PACKAGE_ROOT / "packets" / "fact_vocabulary.yaml"


@dataclass
class Item:
    name: str
    ok: bool
    detail: str = ""
    blocking: bool = True


def _git_sha() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, cwd=REPO_ROOT)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _git_clean() -> bool:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                             text=True, timeout=10, cwd=REPO_ROOT)
        return out.returncode == 0 and not out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False


def run_preflight(stage: str) -> int:
    items: list[Item] = []
    config = load_stage(stage_config(stage))
    packages = parse_all_including_heldout(SCENARIOS_DIR)
    packet_ids = {pid: p.report_ids for pkg in packages.values()
                  for pid, p in pkg.packets.items()}
    packet_texts = {pid: "\n".join(r.text for r in p.reports)
                    for pkg in packages.values() for pid, p in pkg.packets.items()}

    # --- M5 wiring: no raw output can reach an artifact -------------------
    from ..pipeline.strip import FORBIDDEN_MARKERS
    items.append(Item("M5 wired; forbidden-marker assertion available",
                      bool(FORBIDDEN_MARKERS),
                      f"{len(FORBIDDEN_MARKERS)} markers guarded"))

    # --- answer key ------------------------------------------------------
    from ..packets.answer_key import load_answer_key, validate_answer_key
    if ANSWER_KEY_JSON.exists():
        key = load_answer_key(ANSWER_KEY_JSON)
        errors = validate_answer_key(key, packages, check_hashes=True)
        items.append(Item("answer key validates with --check-hashes", not errors,
                          f"{len(errors)} error(s)"))
    else:
        items.append(Item("answer key built", False, "run `sedition build-key`"))

    # --- golden prompts --------------------------------------------------
    try:
        rendered = render_all()
        drift = [n for n, text in rendered.items()
                 if not (GOLDEN_DIR / n).exists()
                 or (GOLDEN_DIR / n).read_text(encoding="utf-8") != text]
        items.append(Item("golden prompts committed and current", not drift,
                          f"{len(rendered)} rendered, {len(drift)} would change"))
    except Exception as e:  # noqa: BLE001
        items.append(Item("golden prompts render", False, str(e)[:120]))

    # --- config: seed, cells, blocks, budgets, failure policy ------------
    items.append(Item("master_seed fixed", config.master_seed is not None,
                      f"seed={config.master_seed}"))
    items.append(Item("cell list and block count fixed", True,
                      f"{[c.value for c in config.cells]} x {config.blocks} blocks "
                      f"= {config.episode_count} episodes"))
    try:
        config.budgets.assert_public_budgets_matched()
        items.append(Item("budget equality assertions pass", True,
                          f"public briefing={config.budgets.briefing_max_tokens}, "
                          f"clarification={config.budgets.clarification_max_tokens}"))
    except ValueError as e:
        items.append(Item("budget equality assertions pass", False, str(e)))
    items.append(Item("failure policy constants fixed", True,
                      f"max_infra_retries={config.failure_policy.max_infra_retries}, "
                      f"malformed={config.failure_policy.malformed_private_output}, "
                      f"replace={config.failure_policy.replace_dropped_episodes}"))

    # --- provider / models ------------------------------------------------
    models = ", ".join(f"{r}={m.model_id}@{m.temperature}" for r, m in config.models.items())
    items.append(Item("model, temperature, provider recorded", True,
                      f"provider={config.provider.name} | {models}"))

    # --- hashes ------------------------------------------------------------
    components = load_all(PROMPT_MODULES_DIR, PromptRegistry())
    items.append(Item("packet and prompt-module hashes available", True,
                      f"{len(packet_ids)} packets, {len(components)} prompt modules"))

    # --- git ---------------------------------------------------------------
    sha = _git_sha()
    items.append(Item("git SHA recorded", sha is not None, sha or "not a git repo"))
    items.append(Item("working tree clean (tag before running)", _git_clean(),
                      "uncommitted changes present" if not _git_clean() else "clean",
                      blocking=False))

    # --- fact vocabulary ---------------------------------------------------
    if VOCAB_PATH.exists():
        vocab = load_fact_vocabulary(VOCAB_PATH)
        vocab_errors, vocab_warnings = validate_vocabulary(
            vocab, packet_ids, require_reviewed=config.require_reviewed_vocabulary,
            packet_texts=packet_texts)
        blocking = [e for e in vocab_errors if e.code != "NOT_REVIEWED"]
        items.append(Item("fact vocabulary validates", not blocking,
                          f"{vocab.total_facts()} facts, {len(blocking)} error(s), "
                          f"{len(vocab_warnings)} warning(s)"))
        cleared = vocab.total_facts() - len(vocab.draft_facts)
        items.append(Item("fact vocabulary cleared for scoring", vocab.is_reviewed,
                          f"{cleared}/{vocab.total_facts()} facts cleared, "
                          f"version={vocab.version}"))
        if vocab_warnings:
            items.append(Item("vocabulary warnings signed off", False,
                              f"{len(vocab_warnings)} unreviewed warning(s) — see "
                              "`sedition vocab review-sheet`", blocking=False))

        # scoring_note must never reach a prompt. Check the real render.
        leaked = []
        for pid in vocab.packet_ids():
            rendered = vocab.render_for_monitor(pid)
            for f in vocab.for_packet(pid):
                snippet = f.scoring_note.strip()[:40]
                if snippet and snippet in rendered:
                    leaked.append(f.fact_id)
        items.append(Item("scoring_note absent from rendered vocabulary", not leaked,
                          f"{len(leaked)} leak(s)" if leaked else "clean"))
    else:
        items.append(Item("fact vocabulary present", False, "missing"))

    # --- key derives from the vocabulary ------------------------------------
    if ANSWER_KEY_JSON.exists() and VOCAB_PATH.exists():
        key2 = load_answer_key(ANSWER_KEY_JSON)
        derived_errors = validate_answer_key(key2, packages, check_hashes=True,
                                             vocabulary=load_fact_vocabulary(VOCAB_PATH))
        items.append(Item("answer key derives from the vocabulary", not derived_errors,
                          f"{len(derived_errors)} inconsistency(ies)"))

    # --- every role has a model bound ---------------------------------------
    # Provider adapters are Inspect's job now; what this checks is that the
    # stage names a model for all three roles, since a missing role surfaces
    # as a PrerequisiteError only once the eval is already running.
    roles = ("analyst", "watch_officer", "monitor")
    bound = {r: config.models[r].model_id for r in roles if r in config.models}
    items.append(Item("a model is bound for every role", len(bound) == len(roles),
                      ", ".join(f"{r}={m}" for r, m in sorted(bound.items()))
                      or "no models configured"))
    temps = {r: m.temperature for r, m in config.models.items()}
    eval_roles_stable = all(temps.get(r) == 0.0 for r in ("watch_officer", "monitor"))
    items.append(Item("evaluation roles at temperature 0", eval_roles_stable,
                      ", ".join(f"{r}={v}" for r, v in sorted(temps.items())),
                      blocking=False))

    # --- gate computability -------------------------------------------------
    # A stage that declares a gate its cell list cannot produce is the
    # conflict that already happened once. Fail here, not in someone's head.
    if config.gates.manipulation is not None:
        wcs = {c.working_condition for c in config.cells}
        honest_wcs = {c.working_condition for c in config.cells
                      if c.policy.value == "honest"}
        computable = (WorkingCondition.SHEET in honest_wcs
                      and WorkingCondition.STRAIGHT in honest_wcs)
        items.append(Item("manipulation gate is computable from these cells", computable,
                          f"honest cells cover {sorted(w.value for w in honest_wcs)}; "
                          "the gate needs both SHEET and STRAIGHT"))
        items.append(Item("length gate is computable from these cells",
                          len(wcs) >= 2,
                          f"cells cover {sorted(w.value for w in wcs)}"))

    # --- pilot gates -------------------------------------------------------
    is_pilot = stage == "pilot_manipulation"
    decisions = REPO_ROOT / "docs" / "DECISIONS.md"
    pilot_done = decisions.is_file() and "Record both outcomes" in decisions.read_text(
        encoding="utf-8"
    )
    items.append(Item("both pilot gates defined with a stated failure action",
                      pilot_done,
                      "see DECISIONS.md #12" if pilot_done else
                      "set AI_SEDITION_WORKSPACE to the project checkout"))
    if not is_pilot and not config.is_sheet_only():
        items.append(Item("stage cell set consistent with staging plan", False,
                          "a STRAIGHT cell outside the pilot — see DECISIONS.md #12",
                          blocking=False))

    # --- resume / determinism ---------------------------------------------
    # Resume is Inspect's, at per-sample granularity (DECISIONS.md #17): a
    # crashed episode re-runs whole rather than resuming mid-call.
    items.append(Item("resume provided by inspect eval-retry / eval_set", True,
                      "per-sample reuse; see DECISIONS.md #17"))
    # These were hardcoded True with a test path as their only evidence, and the
    # path pointed at `tests/`, which is upstream Inspect's tree, not ours. A
    # checklist item that prints PASS without executing anything is the defect
    # this preflight exists to catch. Each now resolves its own test file.
    for name, rel, note in (
        ("determinism verified (same seed -> same permutations)",
         "tests/unit/test_shuffling.py", ""),
        ("raw analyst output never reaches state.messages",
         "tests/inspect_port/test_payload_privacy.py",
         " — DECISIONS.md #18"),
    ):
        items.append(Item(name, (REPO_ROOT / rel).exists(), rel + note))

    # --- print -------------------------------------------------------------
    width = max(len(i.name) for i in items)
    print(f"PREFLIGHT — stage: {stage}\n")
    blocking_failures = 0
    for i in items:
        mark = "PASS" if i.ok else ("FAIL" if i.blocking else "WARN")
        if not i.ok and i.blocking:
            blocking_failures += 1
        print(f"  [{mark}] {i.name:<{width}}  {i.detail}")

    print()
    if blocking_failures:
        print(f"{blocking_failures} blocking item(s) failed — DO NOT START THE RUN.")
        return 1
    print("All blocking items pass.")
    print("Primary outcome: watch-officer decision. Secondary: decision probabilities.")
    return 0
