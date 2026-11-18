"""Typed stage configuration. The YAML is validated on load, never
dict-indexed by callers — a typo in a key fails at load with a field name,
not three modules later with a KeyError.

A stage config is the preregistration artifact for the run it drives. Every
locked decision that can be checked statically is checked here, and a config
that violates one refuses to load rather than warning.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..enums import Cell


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str
    temperature: float = Field(ge=0.0, le=2.0)
    #: USD per MILLION tokens. Optional, but without them the spend guard
    #: cannot convert real token usage into dollars and will say so loudly
    #: rather than reporting a quietly low total.
    usd_per_m_input: float | None = Field(default=None, ge=0)
    usd_per_m_output: float | None = Field(default=None, ge=0)


class Budgets(BaseModel):
    """SHEET is ONE call whose raw allowance is private allowance + public
    budget. The PUBLIC component is the same integer in both working
    conditions — asserted below, because if it ever diverges, part of the
    working-condition comparison is output length rather than procedure.
    See DECISIONS.md #2.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    briefing_max_tokens: int = Field(gt=0)
    sheet_allowance_tokens: int = Field(gt=0)
    clarification_max_tokens: int = Field(gt=0)
    clarification_check_allowance_tokens: int = Field(gt=0)
    briefing_word_budget: int = Field(gt=0)

    def max_output_tokens(self, working_condition: str, turn: str) -> int:
        if turn == "briefing":
            public, private = self.briefing_max_tokens, self.sheet_allowance_tokens
        elif turn == "clarification":
            public, private = (self.clarification_max_tokens,
                               self.clarification_check_allowance_tokens)
        else:
            raise ValueError(f"unknown turn {turn!r}")
        if working_condition == "SHEET":
            return public + private
        if working_condition == "STRAIGHT":
            return public
        raise ValueError(f"unknown working_condition {working_condition!r}")

    def assert_public_budgets_matched(self) -> None:
        """Hard assertion, run at run start. Fails the run, does not warn."""
        for turn in ("briefing", "clarification"):
            sheet = self.max_output_tokens("SHEET", turn)
            straight = self.max_output_tokens("STRAIGHT", turn)
            private = (self.sheet_allowance_tokens if turn == "briefing"
                       else self.clarification_check_allowance_tokens)
            if sheet - private != straight:
                raise ValueError(
                    f"public {turn} allowance differs between SHEET and STRAIGHT: "
                    f"{sheet - private} vs {straight}. Part of the working-condition "
                    "comparison would be output length."
                )


class FailurePolicy(BaseModel):
    """Frozen before any real run. Changing it after seeing data invalidates
    the preregistration. See DECISIONS.md #4."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_infra_retries: int = Field(ge=0)
    malformed_private_output: str
    monitor_json_max_retries: int = Field(ge=0)
    replace_dropped_episodes: bool

    @field_validator("malformed_private_output")
    @classmethod
    def _locked_invalid_no_retry(cls, v: str) -> str:
        if v != "invalid_no_retry":
            raise ValueError(
                "malformed_private_output must be 'invalid_no_retry' (locked: "
                "forwarding a malformed remainder risks exposing the private "
                "artifact; re-prompting changes the sampling distribution)")
        return v

    @field_validator("replace_dropped_episodes")
    @classmethod
    def _locked_drop_not_replace(cls, v: bool) -> bool:
        if v is not False:
            raise ValueError(
                "replace_dropped_episodes must be false (locked: re-rolling until "
                "the model produces a usable output selects on model behavior)")
        return v


class WatchOfficerConfig(BaseModel):
    """Watch-officer behaviour that is a research choice, not an implementation
    detail."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Whether the FINAL turn receives the officer's own first-round output.
    #: Realistic and it reduces re-derivation noise, but it ANCHORS: an officer
    #: that wrote not_met may be reluctant to move. Defaults to current
    #: behaviour so nothing changes silently. The decision of whether stage 0
    #: runs both arms is DECISIONS.md #15 — and it cannot be answered on the
    #: pilot, because honest cells rarely request clarification, which is what
    #: makes them honest.
    return_first_round_assessment: bool = True


class GateThresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_mean_word_delta_pct: float | None = None
    derived_drop_min_pp: float | None = None
    atomic_delta_max_pp: float | None = None


class Gates(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    length: GateThresholds | None = None
    manipulation: GateThresholds | None = None
    #: Never pooled. A flat result across SS and MS is itself a signal.
    report_by: str = "packet"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    #: Hard gate. Must ALSO be passed on the CLI — two locks, deliberately.
    allow_real_calls: bool = False


class StageConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    master_seed: int
    blocks: int = Field(gt=0)
    cells: tuple[Cell, ...] = Field(min_length=1)
    models: dict[str, ModelSpec]
    provider: ProviderConfig
    budgets: Budgets
    failure_policy: FailurePolicy
    purpose: str = ""
    max_parallel_cells: int = Field(default=4, ge=1)
    require_reviewed_vocabulary: bool = False
    #: Hard ceiling. The driver stops cleanly when real recorded usage
    #: reaches it; the run stays resumable.
    max_usd: float | None = Field(default=None, gt=0)
    watch_officer: WatchOfficerConfig = WatchOfficerConfig()
    gates: Gates = Gates()

    source_path: Path | None = None
    source_sha256: str | None = None

    @field_validator("cells")
    @classmethod
    def _no_duplicate_cells(cls, v: tuple[Cell, ...]) -> tuple[Cell, ...]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate cell ids")
        return v

    @model_validator(mode="after")
    def _check_roles_and_budgets(self) -> StageConfig:
        if set(self.models) != {"analyst", "watch_officer", "monitor"}:
            raise ValueError("models must define exactly analyst, watch_officer, monitor")
        self.budgets.assert_public_budgets_matched()
        return self

    @property
    def episode_count(self) -> int:
        return 3 * 2 * len(self.cells) * self.blocks  # 3 events x 2 versions

    def is_sheet_only(self) -> bool:
        from ..enums import WorkingCondition
        return all(c.working_condition is WorkingCondition.SHEET for c in self.cells)


def load_stage(path: str | Path) -> StageConfig:
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    data["source_path"] = path
    data["source_sha256"] = hashlib.sha256(raw).hexdigest()
    return StageConfig.model_validate(data)
