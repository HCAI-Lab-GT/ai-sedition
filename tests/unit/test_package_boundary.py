from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

from sedition.storage import paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_project_uses_only_public_inspect_modules() -> None:
    private: list[str] = []
    roots = (SOURCE_ROOT, PROJECT_ROOT / "scripts", PROJECT_ROOT / "tests")
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            for module in _imports(path):
                parts = module.split(".")
                if parts[0] == "inspect_ai" and any(part.startswith("_") for part in parts[1:]):
                    private.append(f"{path.relative_to(PROJECT_ROOT)}: {module}")

    assert not private, "private Inspect imports:\n" + "\n".join(private)


def test_sensitive_package_data_is_explicitly_allowlisted() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert package_data["sedition_inspect"] == ["data/observed_priors.json"]
    sensitive_prefixes = ("config/", "packets/", "resources/")
    assert all(
        "*" not in pattern
        for pattern in package_data["sedition"]
        if pattern.startswith(sensitive_prefixes)
    )


def test_source_has_no_legacy_adapter_namespace() -> None:
    legacy = ".".join(("settings", "sedition_briefing"))
    hits = [
        str(path.relative_to(PROJECT_ROOT))
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
        if legacy in path.read_text(encoding="utf-8")
    ]

    assert not hits, "legacy adapter namespace remains in:\n" + "\n".join(hits)


def test_immutable_resources_are_package_local() -> None:
    assert paths.RESOURCES_ROOT == paths.PACKAGE_ROOT / "resources"
    assert paths.SCENARIOS_DIR == paths.RESOURCES_ROOT / "scenarios"
    assert paths.HELDOUT_SCENARIOS_DIR == paths.RESOURCES_ROOT / "scenarios_heldout"
    assert paths.TWINS_DIR == paths.RESOURCES_ROOT / "twins"
    assert paths.ANSWER_KEY_JSON == paths.RESOURCES_ROOT / "answer_key.json"


def test_generated_outputs_are_outside_the_package() -> None:
    assert not paths.BUILD_DIR.is_relative_to(paths.PACKAGE_ROOT)
    assert not paths.GOLDEN_DIR.is_relative_to(paths.PACKAGE_ROOT)
    assert not paths.DEFAULT_RUNS_ROOT.is_relative_to(paths.PACKAGE_ROOT)


def test_packaged_key_uses_relocatable_source_ids() -> None:
    key = json.loads(paths.ANSWER_KEY_JSON.read_text(encoding="utf-8"))
    source_ids = [*key["sources"], *(packet["source_file"] for packet in key["packets"].values())]

    assert source_ids
    assert all(not Path(source_id).is_absolute() for source_id in source_ids)
