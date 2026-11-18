# Released data

For analysis, use the [E01–E03 dataset](docs/datasets/matrix_480_e01e03.json.gz).

## What the data contains

This is the dataset for **The AI Sedition Acts: Sabotage-by-Omission in LLM
Briefing Pipelines**. It measures whether an analyst can omit decision-relevant
relationships from a briefing, whether the watch officer's decision changes,
and whether a monitor detects the distortion.

The 480 episodes cover three fictional events (E01-E03), two evidence forms
(MS and SS), threat and control variants, and four analyst conditions (honest,
degraded, basic saboteur, and strategic saboteur). These factors produce 48
cells with 10 episodes each.

## Which files to use

| File | Purpose |
|---|---|
| `docs/datasets/matrix_480_e01e03.json.gz` | Full processed records using the paper's E01-E03 labels. Includes public briefings, officer assessments and decisions, monitor outputs, mechanical scores, usage, and strategic-selection fields. |
| `docs/results/matrix-480-2026-08-27/episode_log.jsonl` and `episode_log.csv` | Compact per-episode results for analysis. |
| `docs/results/matrix-480-2026-08-27/run-summary.json` and `RUN_LOG.md` | The 48-cell aggregate results in machine-readable and readable form. |
| `docs/results/matrix-480-2026-08-27/run-manifest.json` | Model identifiers, temperatures, prompt selections, decision threshold, and matrix dimensions. |
| `SHA256SUMS` | Integrity checksums for the distributed result files. |

Raw provider `.eval` containers are not distributed. They are not needed to
reconstruct the tables from the processed records.

## Verify the tables without model calls

From the repository root:

```bash
python scripts/verify_results.py
```

The verifier checks release-file integrity, episode counts and identifiers,
48 cells at n=10, and the absence of invalid/refused/errored records. It then
reconstructs `run-summary.json` from the compact JSONL. It does not yet compare
every compact outcome with its full record or verify the complete mapping
between the two full-record files.

## Recorded execution settings

| Setting | Recorded value |
|---|---|
| Analyst | `azureai/DeepSeek-V4-Pro`, temperature 0.7 |
| Watch officer and monitor | `azureai/DeepSeek-V4-Flash`, temperature 0.0 |
| Strategic overlay | `shade_v17` |
| Officer and notification standard | `v6_assessor`; `notification_standard_v3_relational`; k=1 |
| Report-order master seed | 20260814 |
| E01/E03 report-order blocks | 5001-5005 and 6001-6005 |
| E02 report-order blocks | 11001-11005 and 12001-12005 |
| Briefing response-token cap | E01/E03: 10,000; E02: 8,000 |
| Other response-token caps | Strategic selection: 4,000; officer: 2,600; monitor: 4,000 |
| Prompt word budget | 1,300 words; over-budget outputs were flagged and retained |
| Model sampling seed | Not set; the master seed controls report order only |
| Collection runtime recorded in the dataset | Python 3.14.6; Inspect AI `0.3.259.dev38+gcc5f7a63a.d20260815` |
| Release installation | Python >=3.12, CI on 3.12; Inspect AI 0.3.261 |

The paper replay reads report orders directly from the E01–E03 archive.
Each episode records its order and its checksum. The runner uses separate
event groups to apply the briefing caps listed above.

We reran two episodes because their initial outputs could not be scored.
The 480 reported episodes include the results of those reruns.

## Checking the paper's dataset checksum

[SHA256SUMS](SHA256SUMS) identifies the archived copy that matches the paper's
checksum. The E01–E03 dataset contains the same 480 episodes with the paper's
labels, including within briefing text. It omits the provider log filename and
recomputes the stimulus and report-order hashes for the released identifiers.
Appendix J gives the identifier mapping.

## Scope and limitations

All scenarios and operational details are fictional. The dataset contains no
provider credentials or human-subject data. The code and included research
data use the repository's MIT license.

The study covers three events and one decision standard; it does not establish
performance in real organizations. Hosted-model outputs can differ between
runs because no model sampling seed was set and deployments can change.
`KNOWN_LIMITATIONS.md` describes monitor-visible scoring anchors and the
static control-gate limitation. The mock provider checks execution and is not
evidence of model behavior.
