from __future__ import annotations

from importlib.metadata import entry_points, version


def test_distribution_version_is_project_scoped() -> None:
    assert version("ai-sedition") == "0.1.0"


def test_adapter_namespace_is_the_inspect_entry_point() -> None:
    matches = [
        entry_point
        for entry_point in entry_points(group="inspect_ai")
        if entry_point.name == "sedition_inspect"
    ]

    assert len(matches) == 1
    assert matches[0].value == "sedition_inspect._registry"
    assert matches[0].load().__name__ == "sedition_inspect._registry"
