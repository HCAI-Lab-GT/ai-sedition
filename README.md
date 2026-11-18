# The AI Sedition Acts: Sabotage-by-Omission in LLM Briefing Pipelines

**Advik Talasila, Calvin Supasanya, Dennis Andelman, Vishwesh Chinthukumar,
and Glenn Matlin.** The first four authors contributed equally; their order
was decided by random draw. Glenn Matlin is the corresponding author.

This repository contains the code, fictional E01-E03 packet suite, prompts,
scoring rules, tests, and processed episode-level data for the paper's
480-episode evaluation. Inspect AI is installed as a released dependency;
it is not vendored or modified here.

For analysis, use the [E01–E03 dataset](docs/datasets/matrix_480_e01e03.json.gz).
It contains all 480 episodes and uses the scenario names in the paper.

## What is included

- The executable evaluation package under `src/`.
- Six E01-E03 packets: three scenarios in MS and SS form.
- Matched threat and control variants.
- Honest, degraded, basic-saboteur, and strategic-saboteur analyst conditions.
- The final 480 processed episode records and a 48-cell aggregate summary.
- Locked dependencies, golden prompts, tests, and an offline mock provider.

The processed dataset includes every public briefing, officer criterion
assessment and decision, monitor result, mechanical score, model-usage record,
and recorded private strategic-selection field needed for the released
analyses. Raw provider `.eval` archives and credentials are not included. They
are not required by the offline result verifier or test suite.

See the [data card](DATA_CARD.md) for the recorded settings and file descriptions.

## Install

Python 3.12 or newer is supported. The CI and recorded verification use Python
3.12.

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv sync --locked --dev
```

With pip:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install "pytest>=8.3,<10"
```

The development dependencies are a PEP 735 dependency group, not a package
extra, so `pip install -e ".[dev]"` is not supported. A pip installation also
resolves dependencies independently rather than reproducing `uv.lock`.

## Verify the released results

This command requires no provider key and makes no network calls:

```bash
uv run python scripts/verify_results.py
```

It verifies the release checksums, the 480 unique E01-E03 episodes, all 48
cells at n=10, the absence of invalid/refused/errored records, and reproduces
`run-summary.json` from the compact episode JSONL.

## Verify the code

```bash
uv run sedition build-packets
uv run sedition build-key
uv run sedition render-golden --check
uv run pytest tests -p no:randomly
```

`build-key` reports six documented vocabulary warnings. The suite also reports
nine strict expected failures for the two open secondary-measurement
limitations described in `KNOWN_LIMITATIONS.md`.

Run one installed Inspect task without a provider key:

```bash
uv run inspect eval sedition_briefing \
  --model sedition_mock/model \
  --model-role analyst=sedition_mock/model \
  --model-role watch_officer=sedition_mock/model \
  --model-role monitor=sedition_mock/model \
  --limit 1 --display none --log-dir logs/offline-smoke
```

The task must be addressed by its registry name, `sedition_briefing`.

## Replay the paper's experiment

From the repository root, install the locked dependencies and preview the replay:

```bash
uv sync --locked
uv run python scripts/replay_paper.py
```

The preview checks all 60 recorded report orders and the briefing caps for
both groups. E01 and E03 run 320 episodes with a 10,000-token cap. E02 runs
160 episodes with an 8,000-token cap. Every role uses the models, temperatures,
and prompt selections listed in the data card.

For a hosted run, put your Azure AI Foundry credentials for the DeepSeek
deployments in a local `.env` at the repository root:

```text
AZUREAI_API_KEY=...
AZUREAI_BASE_URL=...
```

Point the runner at that directory, then launch the paid 480-episode replay:

```bash
export AI_SEDITION_WORKSPACE="$PWD"
uv run python scripts/replay_paper.py --run
```

Both groups pass preflight before the first model request. To check local
provider setup only, use `--check-provider`. Azure checks deployment access
on the first live request. Results go under `logs/paper-replay/E01-E03/`
and `logs/paper-replay/E02/`. Use `--log-root` to select a different output
directory. Model responses can vary because the study used hosted deployments
and left the model sampling seed unset.

## Repository map

- `src/sedition/`: packet construction, prompts, scoring, and resources.
- `src/sedition_inspect/`: the Inspect extension.
- `tests/`: unit, integration, and Inspect-port regression tests.
- `golden/`: the committed prompt-rendering boundary.
- `scripts/run_two_axis.py`: hosted-model matrix runner.
- `scripts/verify_results.py`: offline result verifier.
- `docs/datasets/matrix_480_e01e03.json.gz`: full processed records.
- `docs/results/matrix-480-2026-08-27/`: compact records and summary.
- `DATA_CARD.md`: released-data documentation.

The packet suite is fictional and contains no real vulnerabilities,
credentials, access instructions, or personal data.

## License

The code and included research data are released under the MIT License. Inspect
AI remains a separately installed dependency under its own license.
