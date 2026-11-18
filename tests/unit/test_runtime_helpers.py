from __future__ import annotations

import os

import anyio
from inspect_ai.model import get_model

from sedition_inspect import mock_model
from sedition_inspect.concurrency import collect_concurrently
from sedition_inspect.environment import load_project_dotenv


def test_collect_concurrently_preserves_input_order() -> None:
    async def collect() -> list[int]:
        async def delayed(value: int) -> int:
            await anyio.sleep((3 - value) / 100)
            return value

        return await collect_concurrently(
            [lambda value=value: delayed(value) for value in range(3)]
        )

    assert anyio.run(collect) == [0, 1, 2]


def test_load_project_dotenv_uses_the_declared_workspace(tmp_path, monkeypatch) -> None:
    variable = "AI_SEDITION_DOTENV_TEST"
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AI_SEDITION_WORKSPACE", str(tmp_path))
    (tmp_path / ".env").write_text(f"{variable}=loaded\n", encoding="utf-8")

    assert load_project_dotenv()
    assert os.environ[variable] == "loaded"


def test_load_project_dotenv_does_not_search_the_current_directory(tmp_path, monkeypatch) -> None:
    variable = "AI_SEDITION_DOTENV_CWD_TEST"
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("AI_SEDITION_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{variable}=unexpected\n", encoding="utf-8")

    assert not load_project_dotenv()
    assert variable not in os.environ


def test_project_mock_provider_generates_without_external_tokenizers() -> None:
    async def generate():
        model = get_model(mock_model.MODEL, memoize=False)
        output = await model.generate("offline smoke")
        token_count = await model.api.count_text_tokens("offline smoke")
        return model, output, token_count

    model, output, token_count = anyio.run(generate)

    assert str(model) == mock_model.MODEL
    assert output.completion == mock_model.DEFAULT_OUTPUT
    assert output.usage is not None
    assert output.usage.total_tokens == 2
    assert token_count == 2
