"""What a bound model's provider can actually be relied on to do.

Inspect providers differ in which `GenerateConfig` fields they honour, and a
provider that does not support a field DROPS IT SILENTLY — no exception, no
log line. For most fields that is a nuisance. For `response_schema` it is a
data-quality risk, because the watch officer's decision is parsed as JSON.

The concrete case this module exists for: `azureai` (Azure AI Foundry's
non-OpenAI catalog — Llama, Mistral, Phi). Its `completion_params` forwards
frequency_penalty, presence_penalty, temperature, top_p, max_tokens, stop and
seed, and nothing else — `response_schema` is never read. Verified at
src/inspect_ai/model/_providers/azureai.py:288-308; the one `json_schema_dump`
call in that file (line 543) builds TOOL parameter schemas, not a response
format.

WHAT THAT MEANS HERE, precisely — it is narrower than it first looks:

* Forced JSON was never the only mechanism. watch_officer_v2.md §10 already
  says "Return one valid JSON object and nothing else. No Markdown, no code
  fences", and `parse_watch_officer` strips fences anyway. So the officer
  degrades from GUARANTEED JSON to REQUESTED JSON, not to free text.
* Failure is loud per episode, not silent: an unparseable officer turn raises
  HarnessError, the solver flags WO_MALFORMED and sets `invalid`.
* The real hazard is therefore SURVIVORSHIP, not corruption. If a weaker model
  emits clean JSON most of the time, the episodes that survive are filtered on
  the officer's JSON compliance — which is not independent of how it reasons.
  Watch the WO_MALFORMED rate; if it is non-zero, the surviving sample is
  biased and the run should not be pooled with a forced-JSON run.
"""
from __future__ import annotations

#: Providers verified BY READING THE SOURCE to map `response_schema` onto a
#: real API parameter. `openai` and its compatible subclasses reach it through
#: the shared `openai_completion_params` (src/inspect_ai/model/_openai.py:363).
_FORCED_JSON_YES = frozenset({
    "openai", "openai-api", "anthropic", "google", "vertex", "bedrock",
    "grok", "groq", "mistral", "together", "sagemaker",
})

#: Providers verified NOT to read `response_schema` at all.
_FORCED_JSON_NO = frozenset({"azureai"})

#: `azureai` DOES forward seed (azureai.py:305-306) and temperature (:294-295),
#: so determinism pinning survives the switch. Listed explicitly because the
#: obvious assumption — "it drops response_schema so it probably drops seed
#: too" — is wrong, and acting on it would mean pinning nothing.
_SEED_NO = frozenset({"mockllm", "none", "sedition_mock"})

#: Canned outputs; capability questions do not apply.
_NOT_APPLICABLE = frozenset({"mockllm", "none", "sedition_mock"})


#: What each provider needs in the environment, as groups of alternatives —
#: one variable from each group must be set. Read off the providers' own
#: resolution order: azureai takes its key from AZURE_API_KEY or
#: AZUREAI_API_KEY and its endpoint from AZURE_ENDPOINT_URL,
#: AZUREAI_ENDPOINT_URL or AZUREAI_BASE_URL (azureai.py:85-92, 184-199).
_REQUIRED_ENV: dict[str, tuple[tuple[str, ...], ...]] = {
    "openai": (("OPENAI_API_KEY",),),
    "azureai": (
        ("AZUREAI_API_KEY", "AZURE_API_KEY"),
        ("AZUREAI_BASE_URL", "AZUREAI_ENDPOINT_URL", "AZURE_ENDPOINT_URL"),
    ),
    "anthropic": (("ANTHROPIC_API_KEY",),),
    "mockllm": (),
    "none": (),
    "sedition_mock": (),
}


def provider_of(model_id: str) -> str:
    """`azureai/Llama-3.3-70B` -> `azureai`."""
    return str(model_id).split("/", 1)[0].lower()


def model_args_for(model_id: str) -> dict:
    """Provider quirks that must be turned off for this harness.

    `azureai` switches TOOL EMULATION on automatically for any Llama
    (azureai.py:211-213) and then rewrites the input through a Llama31Handler,
    which prepends a system message telling the model it is a function-calling
    assistant and must answer inside <tool_call> XML — even when the tool list
    is empty, which it always is here. Nothing in this experiment uses tools.

    Measured on the real watch-officer prompt against Llama-4-Scout:

        emulation on (default)   287 output tokens, EMPTY completion
        emulate_tools=False      482 output tokens, the actual decision

    With emulation on, the handler reads the model's reply as a malformed
    tool call and discards it, so the episode dies with WO_MALFORMED and no
    output to inspect. Nothing warns; the tokens are billed either way.
    """
    if provider_of(model_id) == "azureai":
        return {"emulate_tools": False}
    return {}


def missing_env(model_ids, environ) -> list[str]:
    """Which credentials are absent for this set of models.

    Returns human-readable "one of X / Y" lines. An unknown provider
    contributes nothing rather than a false alarm.
    """
    out: list[str] = []
    for provider in sorted({provider_of(m) for m in model_ids}):
        for group in _REQUIRED_ENV.get(provider, ()):
            if not any(environ.get(v) for v in group):
                out.append(f"{provider}: set {' or '.join(group)}")
    return out


def supports_forced_json(model_id: str) -> bool | None:
    """True / False when verified, None when the provider is unknown here.

    None is deliberately distinct from False: an unverified provider should
    prompt somebody to go and read its source, not be quietly assumed broken.
    """
    p = provider_of(model_id)
    if p in _NOT_APPLICABLE:
        return True
    if p in _FORCED_JSON_NO:
        return False
    if p in _FORCED_JSON_YES:
        return True
    return None


def supports_seed(model_id: str) -> bool | None:
    p = provider_of(model_id)
    if p in _NOT_APPLICABLE:
        return True
    if p in _SEED_NO:
        return False
    return True


#: Roles that actually pass `response_schema`, and therefore actually lose
#: something on a provider that ignores it. Only the watch officer does
#: (solver.py:291). The analyst writes prose and is exempt.
_FORCED_JSON_ROLES = ("watch_officer",)

#: Roles whose output is parsed as JSON but which never requested forced JSON
#: in the first place — the monitor asks in the prompt and RETRIES on a parse
#: failure (scorers.py), recording MONITOR_INVALID only after exhausting them.
#: Nothing is lost by switching provider here, so the note is informational:
#: a weaker model simply burns more retries.
_PROMPT_JSON_ROLES = ("monitor",)


def capability_warnings(roles: dict[str, str]) -> list[str]:
    """Human-readable warnings for a role -> model-id mapping. Empty is good.

    Returns lines rather than calling `warnings.warn` itself so the caller
    decides where they surface; a warning nobody sees is the exact failure
    mode this module exists to prevent.
    """
    out: list[str] = []
    for role in _FORCED_JSON_ROLES:
        model_id = roles.get(role)
        if model_id is None:
            continue
        forced = supports_forced_json(model_id)
        if forced is False:
            out.append(
                f"{role}: {model_id} runs on the '{provider_of(model_id)}' "
                "provider, which ignores response_schema, so forced JSON is "
                "NOT in effect. The model is only ASKED for JSON, by section "
                "10 of the officer prompt. An unparseable turn is flagged "
                "WO_MALFORMED and the episode is marked invalid with no retry, "
                "so CHECK THAT RATE before trusting the run: if it is above "
                "zero the surviving episodes are filtered on JSON compliance, "
                "and must not be pooled with a forced-JSON run."
            )
        elif forced is None:
            out.append(
                f"{role}: {model_id} runs on the unrecognised provider "
                f"'{provider_of(model_id)}'. Whether it honours "
                "response_schema has not been verified — read that provider's "
                "completion_params before relying on the output parsing."
            )
    for role in _PROMPT_JSON_ROLES:
        model_id = roles.get(role)
        if model_id is not None and supports_forced_json(model_id) is not True:
            out.append(
                f"{role}: {model_id} parses as JSON but never used forced JSON, "
                "so nothing is lost by the provider — expect more parse retries "
                "on a weaker model, and MONITOR_INVALID only if they run out."
            )
    for role, model_id in roles.items():
        if supports_seed(model_id) is False:
            out.append(
                f"{role}: {model_id} does not forward seed, so this role is "
                "not seed-reproducible."
            )
    return out
