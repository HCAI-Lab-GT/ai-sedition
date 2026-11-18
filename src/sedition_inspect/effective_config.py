"""The configuration a run will ACTUALLY apply, read out of the code that applies it.

WHY THIS EXISTS. `scripts/run_two_axis.py` wrote the token budgets into
`run-manifest.json` as a hand-kept literal::

    budgets = RAISED_BUDGETS if a.raised_budgets else {
        "selection_max_tokens": 1200, "briefing_max_tokens": 4000,
        "monitor_max_tokens": 1600}

All three numbers were wrong. What executes is the keyword defaults on
`solver.sedition_episode` (selection 4000, briefing 8000) and the module
constant `scorers.MONITOR_MAX_TOKENS` (4000). Those were raised on 2026-08-22
-- each with a comment saying why -- and the literal in the launcher was never
touched. Thirteen of the fourteen manifests committed under `logs/` therefore
record `{1200, 4000, 1600}` for runs that executed at `{4000, 8000, 4000}`.

A hand-written manifest records what somebody believed. This module records
what the code will do, by reading the code: `inspect.signature` for the
solver's keyword defaults, the module constant for the monitor,
`run.MODEL_SETS` for the per-role model and temperature. No literal is left to
drift, and `config_mismatches()` re-derives the whole thing so a manifest can
be checked against the code that wrote it.

WHAT THE INTROSPECTION PROVES, AND WHAT IT DOES NOT
===================================================

It proves the values the code will PASS. It cannot prove what the provider
honours -- azureai silently drops fields it does not implement
(provider_support.py), and `max_tokens` is a cap, not a target.

Three things could still make the recorded numbers wrong, so all three are
checked rather than assumed:

* `task.sedition_briefing` could start threading a budget through as a task
  argument, at which point the solver default stops being the effective value.
  `_assert_task_threads_nothing()` refuses if any budget or temperature
  parameter appears in the task signature.
* the launcher could override the solver by rebinding `task.sedition_episode`
  to a `functools.partial` -- which is exactly what `--raised-budgets` does.
  `solver_keywords()` reads through the partial chain, so the recorded value
  is the post-override one.
* `MODEL_SETS` names a temperature per role, but every call site passes its
  own `temperature=` in `GenerateConfig`, and `Model._resolve_config` merges
  the call-site config OVER the model's own. The call site wins, so the
  `MODEL_SETS` temperature is dead for all three roles. Both values are
  recorded per role, and `temperature_disagreements()` names any role where a
  manifest quoting the declared one would be quoting a number that never
  reached the provider.

`config_mismatches()` compares a recorded manifest against a fresh
recomputation and nothing else. Whether the code is self-consistent is a
different question, asked by `temperature_disagreements()`.
"""
from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Mapping
from typing import Any

from . import scorers as scorers_mod
from . import solver as solver_mod
from . import task as task_mod
from .run import MODEL_SETS

#: Bumped when the shape of `effective_config()` changes, so a manifest written
#: by an older launcher is reported as stale rather than silently compared
#: field by field against a shape it never had.
CONFIG_SCHEMA_VERSION = 1

#: Solver keyword parameters that cap output tokens. Every one is a
#: keyword-only default on `solver.sedition_episode`; none is threaded through
#: `task.sedition_briefing`, which is what makes the default the effective
#: value and is asserted by `_assert_task_threads_nothing()`.
SOLVER_TOKEN_PARAMS: tuple[str, ...] = (
    "selection_max_tokens",
    "briefing_max_tokens",
    "sheet_allowance_tokens",
    "clarification_max_tokens",
    "clarification_check_allowance_tokens",
    "officer_max_tokens",
)

#: Solver keyword parameters that are sampling settings rather than caps.
SOLVER_SAMPLING_PARAMS: tuple[str, ...] = ("analyst_temperature",)

#: The literal the launcher used to write. Kept by name so the regression test
#: can pin "the manifest no longer says this" without restating three numbers
#: that would then have to be maintained in two places.
RETIRED_BUDGET_LITERAL: dict[str, int] = {
    "selection_max_tokens": 1200,
    "briefing_max_tokens": 4000,
    "monitor_max_tokens": 1600,
}

_TEMPERATURE_LITERAL = re.compile(r"temperature\s*=\s*([0-9]+(?:\.[0-9]+)?)\b")


class EffectiveConfigError(RuntimeError):
    """The effective configuration cannot be determined, so nothing may run.

    Raised rather than defaulted: a manifest that guesses is the defect this
    module exists to remove.
    """


class ManifestMismatch(RuntimeError):
    """A recorded manifest disagrees with the configuration the code will apply."""


def _unwrap_partial(fn: Any) -> tuple[Any, dict[str, Any]]:
    """Split a `functools.partial` chain into its target and bound keywords.

    Args:
        fn: A callable, possibly wrapped in one or more `functools.partial`
            layers.

    Returns:
        The innermost callable and the keywords that would be applied to it.
        Outer layers win, matching `functools.partial.__call__`, which updates
        the inner keywords with the outer ones.

    Raises:
        EffectiveConfigError: If a layer binds positional arguments, whose
            effect on keyword values cannot be read.
    """
    bound: dict[str, Any] = {}
    while isinstance(fn, functools.partial):
        if fn.args:
            raise EffectiveConfigError(
                f"positional partial args {fn.args!r} on the solver; the "
                f"effective keyword values cannot be read from a partial that "
                f"binds positionally")
        bound = {**fn.keywords, **bound}
        fn = fn.func
    return fn, bound


def _assert_task_threads_nothing() -> None:
    """Refuse if the task signature has taken over a budget or temperature.

    The solver's keyword default is the effective value only for as long as
    nothing upstream supplies that keyword. `task.sedition_briefing` builds the
    solver by calling `sedition_episode(...)` with an explicit keyword list; if
    a budget ever joins that list it comes from a task argument, the default
    stops being what executes, and this module would start recording a number
    nobody applies.

    Raises:
        EffectiveConfigError: If any parameter this module claims to introspect
            also appears in `task.sedition_briefing`'s signature.
    """
    watched = frozenset(SOLVER_TOKEN_PARAMS) | frozenset(SOLVER_SAMPLING_PARAMS)
    threaded = sorted(watched & frozenset(
        inspect.signature(task_mod.sedition_briefing).parameters))
    if threaded:
        raise EffectiveConfigError(
            f"task.sedition_briefing now takes {threaded}; the solver keyword "
            f"default is no longer the effective value and effective_config.py "
            f"must read the task argument instead")


def solver_keywords() -> dict[str, Any]:
    """Effective keyword values of the solver the task will construct.

    Reads `task.sedition_episode` -- the name `task.sedition_briefing` actually
    calls -- rather than `solver.sedition_episode`, because the launcher's
    `--raised-budgets` path rebinds that module attribute to a
    `functools.partial`. Reading the solver module directly would report the
    pre-override value.

    Returns:
        Every keyword parameter with a default, updated by any keyword bound by
        a `functools.partial` wrapper.

    Raises:
        EffectiveConfigError: If a watched parameter has moved into the task
            signature, if a partial binds positionally, or if an override binds
            a keyword the solver does not accept.
    """
    _assert_task_threads_nothing()
    fn, bound = _unwrap_partial(task_mod.sedition_episode)
    sig = inspect.signature(fn)
    defaults = {
        name: p.default
        for name, p in sig.parameters.items()
        if p.default is not inspect.Parameter.empty
    }
    unknown = sorted(set(bound) - set(sig.parameters))
    if unknown:
        raise EffectiveConfigError(
            f"solver override binds {unknown}, which {getattr(fn, '__name__', fn)!r} "
            f"does not accept; the override would fail at episode construction")
    return {**defaults, **bound}


def _sole_temperature_literal(fn: Any, what: str) -> float:
    """The one hard-coded `temperature=` value in a function's source.

    The officer and the monitor do not take their temperature from a parameter
    -- both call sites write `temperature=0.0` inline. Reading the source is the
    only way to record what they send without making a model call, and it fails
    loudly if the literal is ever changed, duplicated or parameterised.

    Args:
        fn: The function whose source is read.
        what: Human-readable name of the call site, used in error messages.

    Returns:
        The single temperature literal found in the function's source.

    Raises:
        EffectiveConfigError: If the source cannot be read, or does not hold
            exactly one distinct temperature literal.
    """
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError) as exc:
        raise EffectiveConfigError(
            f"cannot read the source of {what}: {exc}") from exc
    found = sorted({float(m) for m in _TEMPERATURE_LITERAL.findall(src)})
    if len(found) != 1:
        raise EffectiveConfigError(
            f"{what} holds {len(found)} distinct temperature literals {found}; "
            f"the effective sampling temperature can no longer be read from "
            f"source and must be recorded some other way")
    return found[0]


def applied_temperatures() -> dict[str, float]:
    """The temperature each role's call site actually sends.

    Returns:
        Role name to the temperature passed in `GenerateConfig` at that role's
        call site. The analyst's is the solver's `analyst_temperature` keyword;
        the officer's and the monitor's are hard-coded literals read from
        source.
    """
    return {
        "analyst": float(solver_keywords()["analyst_temperature"]),
        "watch_officer": _sole_temperature_literal(
            solver_mod._officer_turn, "solver._officer_turn"),
        "monitor": _sole_temperature_literal(
            scorers_mod.monitor_drs, "scorers.monitor_drs"),
    }


def token_budgets() -> dict[str, int]:
    """Every output-token cap this run will apply, post-override.

    Returns:
        The solver's token keywords plus `monitor_max_tokens`, which lives in
        `scorers.MONITOR_MAX_TOKENS` because the monitor is a scorer and takes
        no solver keyword.
    """
    kw = solver_keywords()
    out = {name: int(kw[name]) for name in SOLVER_TOKEN_PARAMS}
    out["monitor_max_tokens"] = int(scorers_mod.MONITOR_MAX_TOKENS)
    return out


def role_config(model_set: str, *, seed: int | None = None) -> dict[str, Any]:
    """Model id, temperature and seed per role, from `MODEL_SETS`.

    Args:
        model_set: A key of `run.MODEL_SETS`.
        seed: The sampling seed `run.build_model_roles` is called with. The
            two-axis launcher passes none, so this is normally `None` and is
            recorded as such rather than omitted -- "no seed" is a fact about
            the run, not a missing field.

    Returns:
        Role name to a record holding the model id, the temperature declared in
        `MODEL_SETS`, the temperature the call site actually sends, whether the
        two agree, and the seed.

    Raises:
        EffectiveConfigError: If `model_set` is not registered.
    """
    if model_set not in MODEL_SETS:
        raise EffectiveConfigError(
            f"unknown model set {model_set!r}; choose from "
            f"{', '.join(sorted(MODEL_SETS))}")
    applied = applied_temperatures()
    out: dict[str, Any] = {}
    for role, entry in MODEL_SETS[model_set].items():
        spec = tuple(entry) if isinstance(entry, (tuple, list)) else (entry,)
        declared = float(spec[1]) if len(spec) > 1 and spec[1] is not None else None
        # No entry carries a third element today. Read rather than assumed
        # absent, so adding a per-role seed to MODEL_SETS lands in the manifest
        # without anyone having to remember this file.
        role_seed = spec[2] if len(spec) > 2 else seed
        out[role] = {
            "model": str(spec[0]),
            "declared_temperature": declared,
            "applied_temperature": applied.get(role, declared),
            "temperature_agrees": (
                declared is not None and applied.get(role, declared) == declared),
            "seed": role_seed,
        }
    return out


def effective_config(model_set: str, *, seed: int | None = None) -> dict[str, Any]:
    """The whole runtime configuration the code decides, rather than the CLI.

    Args:
        model_set: A key of `run.MODEL_SETS`.
        seed: The sampling seed passed to `run.build_model_roles`.

    Returns:
        A JSON-native record: schema version, token budgets, per-role model
        settings, and the source each group was read from. Every value is a
        `str`, `int`, `float`, `bool`, `None`, `list` or `dict`, so the record
        survives a `json.dumps`/`json.loads` round trip unchanged -- which
        `config_mismatches()` relies on.
    """
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "token_budgets": token_budgets(),
        "roles": role_config(model_set, seed=seed),
        "sources": {
            "token_budgets": (
                "inspect.signature(task.sedition_episode) keyword defaults, read "
                "through any functools.partial override; monitor_max_tokens from "
                "scorers.MONITOR_MAX_TOKENS"),
            "declared_temperature": "run.MODEL_SETS",
            "applied_temperature": (
                "solver analyst_temperature keyword; officer and monitor "
                "GenerateConfig literals read from source. The call-site config "
                "is merged OVER the role model's own config "
                "(Model._resolve_config), so the applied value is the one that "
                "reaches the provider."),
            "caveat": (
                "These are the values the harness passes. azureai drops config "
                "fields it does not implement (provider_support.py), and "
                "max_tokens is a cap rather than a target."),
        },
    }


def _brief(value: Any, limit: int = 160) -> str:
    """A `repr` short enough to read in a refusal message.

    Args:
        value: Any value being reported in a finding.
        limit: Maximum characters before the repr is elided.

    Returns:
        `repr(value)`, truncated with a marker naming how much was dropped. A
        whole nested section reported as missing would otherwise print as
        several hundred characters and bury the findings around it.
    """
    text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (+{len(text) - limit} chars)"


def diff_json(recorded: Any, expected: Any, path: str = "") -> list[str]:
    """Every leaf on which two JSON-native records differ.

    Args:
        recorded: The value read back from the manifest.
        expected: The value recomputed from the code.
        path: Dotted key path used to label findings; callers pass "".

    Returns:
        One human-readable line per differing leaf, missing key or extra key.
        Empty when the two are equal.
    """
    here = path or "<root>"
    if isinstance(expected, Mapping) and isinstance(recorded, Mapping):
        out: list[str] = []
        for key in sorted(set(expected) | set(recorded), key=str):
            sub = f"{path}.{key}" if path else str(key)
            if key not in recorded:
                out.append(
                    f"{sub}: missing from the manifest, expected {_brief(expected[key])}")
            elif key not in expected:
                out.append(
                    f"{sub}: recorded {_brief(recorded[key])} but the code sets no such field")
            else:
                out.extend(diff_json(recorded[key], expected[key], sub))
        return out
    if isinstance(expected, list) and isinstance(recorded, list):
        if len(expected) != len(recorded):
            return [f"{here}: recorded {len(recorded)} entries, expected {len(expected)}"]
        rows: list[str] = []
        for i, (rec, exp) in enumerate(zip(recorded, expected)):
            rows.extend(diff_json(rec, exp, f"{path}[{i}]" if path else f"[{i}]"))
        return rows
    if recorded != expected:
        return [f"{here}: recorded {_brief(recorded)}, code applies {_brief(expected)}"]
    return []


def config_mismatches(
    recorded: Mapping[str, Any], model_set: str, *, seed: int | None = None
) -> list[str]:
    """Recompute the effective configuration and report where a manifest differs.

    Args:
        recorded: The `effective_config` section read back from a manifest.
        model_set: The model set the manifest claims to have run.
        seed: The sampling seed the manifest claims.

    Returns:
        Findings, one line each. Empty means the manifest and the code agree.
        This compares the record against the recomputation and nothing else;
        whether the code is itself self-consistent is
        `temperature_disagreements`.
    """
    return diff_json(dict(recorded), effective_config(model_set, seed=seed))


def temperature_disagreements(model_set: str) -> list[str]:
    """Roles whose declared temperature is not the one that reaches the provider.

    `MODEL_SETS` names a temperature per role and `build_model_roles` puts it on
    the role model's `GenerateConfig`. Every call site then passes its own
    `temperature=`, and `Model._resolve_config` merges the call-site config OVER
    the model's own -- so for the analyst, the officer and the monitor alike the
    `MODEL_SETS` value never reaches the provider. Editing it looks like
    changing the sampling and does nothing.

    Deterministic test-double roles are exempt. They return a fixed string, so
    a temperature they ignore is not a drift hazard, and `MODEL_PROVENANCE`
    already records them as "n/a -- deterministic test double".

    Args:
        model_set: A key of `run.MODEL_SETS`.

    Returns:
        One line per role where the two disagree. Empty when they agree.
    """
    out: list[str] = []
    for role, spec in role_config(model_set).items():
        if spec["model"].startswith(("mockllm/", "sedition_mock/")) or spec[
            "temperature_agrees"
        ]:
            continue
        out.append(
            f"{model_set}.{role}: MODEL_SETS declares temperature "
            f"{spec['declared_temperature']!r} but the call site sends "
            f"{spec['applied_temperature']!r}; the call-site config is merged "
            f"over the model's own, so the declared value never reaches "
            f"{spec['model']}")
    return out


def assert_config_matches(
    recorded: Mapping[str, Any], model_set: str, *, seed: int | None = None
) -> None:
    """Fail unless a manifest records the configuration the code will apply.

    Args:
        recorded: The `effective_config` section read back from a manifest.
        model_set: The model set the manifest claims to have run.
        seed: The sampling seed the manifest claims.

    Raises:
        ManifestMismatch: If `config_mismatches` returns anything, listing
            every finding.
    """
    bad = config_mismatches(recorded, model_set, seed=seed)
    if bad:
        raise ManifestMismatch(
            f"run-manifest.json disagrees with the code in {len(bad)} place(s):"
            "\n    " + "\n    ".join(bad))
