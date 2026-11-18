"""Resolve immutable package inputs and writable workspace outputs."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_ROOT = PACKAGE_ROOT / "resources"
SCENARIOS_DIR = RESOURCES_ROOT / "scenarios"
HELDOUT_SCENARIOS_DIR = RESOURCES_ROOT / "scenarios_heldout"
TWINS_DIR = RESOURCES_ROOT / "twins"
PROMPT_MODULES_DIR = PACKAGE_ROOT / "prompts" / "modules"
STAGES_DIR = PACKAGE_ROOT / "config" / "stages"
TARGET_SLOTS = PACKAGE_ROOT / "config" / "target_slots.yaml"
TRIGGER_RULES = PACKAGE_ROOT / "config" / "trigger_rules.md"
PACKETS_JSON = RESOURCES_ROOT / "packets.json"
ANSWER_KEY_JSON = RESOURCES_ROOT / "answer_key.json"
FACT_VOCABULARY_JSON = RESOURCES_ROOT / "fact_vocabulary.json"

WORKSPACE_ROOT = Path(os.environ.get("AI_SEDITION_WORKSPACE", Path.cwd())).expanduser().resolve()
REPO_ROOT = WORKSPACE_ROOT
GOLDEN_DIR = WORKSPACE_ROOT / "golden"
BUILD_DIR = WORKSPACE_ROOT / "build"
BUILT_PACKETS_JSON = BUILD_DIR / "packets.json"
BUILT_ANSWER_KEY_JSON = BUILD_DIR / "answer_key.json"
BUILT_FACT_VOCABULARY_JSON = BUILD_DIR / "fact_vocabulary.json"

DEFAULT_RUNS_ROOT = WORKSPACE_ROOT / "runs"


def stage_config(name: str) -> Path:
    """A stage name resolves to exactly one config file. Accepts either
    'stage0' or 'stage0.yaml'."""
    return STAGES_DIR / (name if name.endswith(".yaml") else f"{name}.yaml")
