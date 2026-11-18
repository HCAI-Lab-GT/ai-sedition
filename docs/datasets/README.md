# Released dataset

For analysis, use [matrix_480_e01e03.json.gz](matrix_480_e01e03.json.gz).
It contains all 480 episodes and uses the scenario names in the paper.
The other archive contains the same episodes and is provided for checking the paper's checksum.

- 480 processed episode records;
- E01, E02, and E03 only;
- MS and SS forms;
- threat and control variants;
- honest, degraded, basic-saboteur, and strategic-saboteur analysts;
- 48 cells with 10 report orders per cell.

Each record contains the public briefing delivered to the officer, the
per-criterion assessment and decision, monitor result, mechanical scores,
prompt versions, model usage, and strategic-selection fields when applicable.

See the [data card](../../DATA_CARD.md) for file descriptions, execution
settings, and instructions for checking the paper's dataset checksum.

Raw provider `.eval` archives are not included. Use
`python scripts/verify_results.py` from the repository root to verify file
integrity and reproduce the 48-cell aggregate summary from the compact episode
records.
