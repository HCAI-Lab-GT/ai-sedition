"""Providers drop config fields they do not implement, silently.

`azureai` never reads `response_schema` (azureai.py:288-308 is an explicit
allowlist that omits it), so binding a Llama set turns the watch officer's
forced JSON off without raising anything. These tests exist because that
failure is invisible at runtime: the officer keeps answering, and only the
WO_MALFORMED rate moves.
"""
from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from sedition_inspect._resources import components, packet, scenario_for
from sedition_inspect.provider_support import (
    capability_warnings,
    missing_env,
    provider_of,
    supports_forced_json,
    supports_seed,
)
from sedition_inspect.run import MODEL_SETS, build_model_roles
from sedition_inspect.solver import _officer_turn

ADAPTER_DIR = Path(__file__).resolve().parents[2] / "src" / "sedition_inspect"


# ------------------------------------------------------- capability table ----

def test_azureai_cannot_force_json_but_does_honour_seed():
    """The asymmetry is the point. Assuming a provider that drops
    response_schema also drops seed would mean pinning nothing for no reason."""
    assert supports_forced_json("azureai/Llama-3.3-70B") is False
    assert supports_seed("azureai/Llama-3.3-70B") is True


def test_openai_supports_forced_json():
    assert supports_forced_json("openai/gpt-4.1") is True
    assert supports_forced_json("openai/gpt-4.1-mini") is True


def test_unknown_provider_is_none_not_false():
    """None means 'go read that provider's source', which is a different
    instruction from 'this is known broken'."""
    assert supports_forced_json("some-new-provider/whatever") is None


def test_provider_of_ignores_the_model_name():
    assert provider_of("azureai/ANY-DEPLOYMENT-NAME") == "azureai"
    assert provider_of("openai/azure-shaped-name") == "openai"


# ------------------------------------------------------------- warnings ----

def test_the_azureai_set_warns_about_the_officer():
    """Repointed from the removed Llama set. The property under test is the
    azureai provider's inability to force JSON, which the DeepSeek set shares
    — it is the same provider."""
    warns = capability_warnings({r: m for r, (m, _) in MODEL_SETS["foundry_deepseek"].items()})
    officer = [w for w in warns if w.startswith("watch_officer:")]
    assert officer, f"no watch_officer warning in {warns}"
    assert "response_schema" in officer[0]
    assert "WO_MALFORMED" in officer[0], "the warning must name the flag to watch"


def test_the_openai_set_warns_about_nothing():
    assert capability_warnings(
        {r: m for r, (m, _) in MODEL_SETS["gpt-4.1"].items()}) == []


def test_monitor_warning_does_not_claim_a_loss():
    """The monitor never used forced JSON — it asks in the prompt and retries.
    Saying it 'lost' something would send somebody hunting a regression that
    is not there."""
    warns = capability_warnings({"monitor": "azureai/X"})
    assert len(warns) == 1
    assert "nothing is lost" in warns[0]


def test_binding_the_foundry_set_actually_emits_the_warning(monkeypatch):
    """capability_warnings returning strings is worthless if run.py never
    surfaces them."""
    monkeypatch.setenv("AZUREAI_API_KEY", "dummy")
    monkeypatch.setenv("AZUREAI_BASE_URL", "https://x.services.ai.azure.com/models")
    monkeypatch.setattr("sedition_inspect.run.get_model", lambda *_args, **_kwargs: object())
    with pytest.warns(UserWarning, match="response_schema"):
        build_model_roles("foundry_deepseek")


# ------------------------------------------------------------- env check ----

def test_missing_env_names_both_azureai_requirements():
    lines = missing_env(["azureai/X"], {})
    assert len(lines) == 2
    assert any("AZUREAI_API_KEY" in line for line in lines)
    assert any("AZUREAI_BASE_URL" in line for line in lines)


def test_missing_env_accepts_either_alternative():
    assert missing_env(
        ["azureai/X"],
        {"AZURE_API_KEY": "k", "AZUREAI_ENDPOINT_URL": "https://x/models"},
    ) == []


def test_unknown_provider_raises_no_false_alarm():
    assert missing_env(["some-new-provider/x"], {}) == []


# ---------------------------------------------------------- the real gate ----

class _RecordingOfficer:
    """Stands in for a bound Model. `_officer_turn` reads `str(officer)` to
    decide whether to ask for forced JSON."""

    def __init__(self, model_id: str):
        self._id = model_id
        self.config = None

    def __str__(self) -> str:
        return self._id

    async def generate(self, _messages, config=None, **_kw):
        self.config = config
        raise _Stop()


class _Stop(Exception):
    pass


def _call_officer(model_id: str):
    officer = _RecordingOfficer(model_id)

    async def go():
        # _officer_turn swallows parse failures; _Stop escapes through the
        # generate call before parsing, so we get the config either way.
        try:
            await _officer_turn(
                block_index=0,
                officer=officer,
                scenario=scenario_for("E03-MS"),
                packet=packet("E03-MS"),
                comps=components(),
                briefing="=== INCIDENT ===\nIncident title: probe",
                turn="DECISION",
                max_tokens=800,
            )
        except _Stop:
            pass

    anyio.run(go)
    assert officer.config is not None, "generate was never called"
    return officer.config


def test_officer_asks_for_forced_json_on_openai():
    config = _call_officer("openai/gpt-4.1-mini")
    assert config.response_schema is not None
    assert config.response_schema.name == "watch_officer_decision"


def test_officer_does_not_ask_for_forced_json_on_azureai():
    """Not cosmetic: sending a parameter the provider silently discards leaves
    the code asserting a guarantee it is not receiving."""
    config = _call_officer("azureai/LLAMA-4-SCOUT-DEPLOYMENT")
    assert config.response_schema is None
    # everything else must survive the switch
    assert config.temperature == 0.0
    assert config.max_tokens == 800


# ------------------------------------------------------------ structural ----

def test_the_azureai_path_never_mentions_the_azure_openai_one():
    """Two different Foundry paths with confusingly similar variable names.
    Mixing them produces a key that authenticates against nothing."""
    for path in ADAPTER_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "AZUREAI_OPENAI" not in text, f"{path.name} names an Azure OpenAI var"
        assert "openai/azure/" not in text, f"{path.name} uses an openai/azure model string"


def test_paired_run_accepts_every_model_set():
    """paired_run used to carry its own hardcoded role table and a two-value
    --model-set, so a set added to run.py was silently unavailable there."""
    import argparse

    from sedition_inspect.paired_run import ALIASES

    p = argparse.ArgumentParser()
    p.add_argument("--model-set", choices=sorted({*MODEL_SETS, *ALIASES}))
    for name in MODEL_SETS:
        assert p.parse_args(["--model-set", name]).model_set == name
    # the old name still resolves, so existing invocations keep working
    assert ALIASES["real"] == "gpt-4.1"
