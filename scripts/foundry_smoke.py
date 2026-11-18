#!/usr/bin/env python3
"""Smoke-test one Azure AI Foundry deployment through Inspect's `azureai/` provider.

Sends a single trivial prompt and prints the RAW completion, unparsed. The
point is to eyeball what actually comes back before committing a real run to
it — this provider ignores `response_schema` entirely, so the shape of its
output is a matter of observation, not guarantee (see
sedition_inspect/provider_support.py).

Usage:
    python scripts/foundry_smoke.py LLAMA-4-SCOUT-DEPLOYMENT
    python scripts/foundry_smoke.py LLAMA-4-SCOUT-DEPLOYMENT --json

`--json` sends the watch officer's actual instruction — "return one valid JSON
object and nothing else" — instead of the trivial prompt, which is the useful
version: it tells you whether this deployment can hold the officer's contract
without forced JSON to fall back on.

Reads AZUREAI_API_KEY and AZUREAI_BASE_URL from the repo-root .env. Note the
base URL for this provider ends in /models — it is NOT the bare resource root
the Azure OpenAI path wants.

Requires: pip install azure-ai-inference
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sedition_inspect.environment import load_project_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

TRIVIAL = "Reply with exactly: OK"
JSON_PROBE = (
    "Return one valid JSON object and nothing else. No Markdown, no code "
    "fences, no text outside the JSON.\n"
    '{"decision": "notify_immediately", "confidence": 0.9}'
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("deployment", help="Foundry deployment name, e.g. Llama-3.3-70B-Instruct")
    p.add_argument("--json", action="store_true",
                   help="send the officer's JSON instruction instead of the trivial prompt")
    args = p.parse_args(argv)

    load_project_dotenv(REPO_ROOT)

    missing = [v for v in ("AZUREAI_API_KEY", "AZUREAI_BASE_URL") if not os.environ.get(v)]
    if missing:
        print(f"Missing: {', '.join(missing)}")
        print(f"Fill them in {REPO_ROOT / '.env'} and retry.")
        return 2

    base_url = os.environ["AZUREAI_BASE_URL"]
    if not base_url.rstrip("/").endswith("/models"):
        print(f"warning: AZUREAI_BASE_URL is {base_url!r}, which does not end in "
              "/models. The azureai provider usually wants the /models endpoint "
              "from the Foundry deployment page. Continuing anyway.")

    try:
        import anyio
        from inspect_ai.model import GenerateConfig, get_model
    except ImportError as e:
        print(f"Missing dependency: {e}")
        return 2

    model_id = f"azureai/{args.deployment}"
    prompt = JSON_PROBE if args.json else TRIVIAL
    print(f"model  : {model_id}")
    print(f"url    : {base_url}")
    print(f"prompt : {prompt.splitlines()[0]}")
    print("-" * 68)

    try:
        model = get_model(model_id, config=GenerateConfig(temperature=0.0, max_tokens=200))
        out = anyio.run(model.generate, prompt)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        if "azure-ai-inference" in str(e) or "azure" in type(e).__name__.lower():
            print("\nIf this is an import error: pip install azure-ai-inference")
        return 1

    raw = out.completion or ""
    print("RAW COMPLETION (verbatim, between the markers):")
    print(f">>>{raw}<<<")
    print("-" * 68)
    print(f"stop reason : {out.stop_reason}")

    if args.json:
        # Report only — the officer's real parser strips fences first; this
        # deliberately does not, so you can see exactly what the model emits.
        try:
            json.loads(raw)
            print("parses as bare JSON : yes")
        except json.JSONDecodeError as e:
            print(f"parses as bare JSON : NO ({e})")
            print("  The officer's parser strips code fences, so fenced JSON is")
            print("  still fine. Prose around the JSON is not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
