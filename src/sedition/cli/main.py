"""The `sedition` CLI — artifact tooling for the experiment environment.

Execution moved to Inspect AI: use `inspect eval sedition_inspect/sedition_briefing`
to run episodes, `inspect view` to read logs, and `inspect score` to re-score
an existing log. What remains here is everything Inspect does not own —
building the read-only packet and answer-key artifacts, rendering golden
prompts, validating the fact vocabulary, and the preflight checklist.
"""


import typer

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="The AI Sedition Acts experiment harness.")


@app.command("build-packets")
def build_packets_cmd() -> None:
    """Parse the scenario markdown into build/packets.json."""
    from ..packets.build_cli import main
    raise typer.Exit(main())


@app.command("validate-key")
def validate_key_cmd(
    check_hashes: bool = typer.Option(False, "--check-hashes",
                                      help="also verify packet and source-file SHA-256 hashes"),
) -> None:
    """Validate build/answer_key.json against the read-only scenario files."""
    from ..packets.answer_key_cli import validate_main
    raise typer.Exit(validate_main(check_hashes=check_hashes))


@app.command("build-key")
def build_key_cmd() -> None:
    """Rebuild build/answer_key.json from the scenario files."""
    from ..packets.answer_key_cli import build_main
    raise typer.Exit(build_main())


@app.command("render-golden")
def render_golden_cmd(
    check: bool = typer.Option(False, "--check",
                              help="fail if any committed golden file would change"),
) -> None:
    """Render every fully-specified prompt at block_index=0 into golden/."""
    from ..prompts.golden import main
    raise typer.Exit(main(check=check))


vocab_app = typer.Typer(help="Fact-vocabulary validation and review.")
app.add_typer(vocab_app, name="vocab")


@vocab_app.command("validate")
def vocab_validate_cmd(
    require_reviewed: bool = typer.Option(False, "--require-reviewed"),
) -> None:
    """Validate the fact vocabulary. Errors block preflight."""
    from .vocab import validate_main
    raise typer.Exit(validate_main(require_reviewed=require_reviewed))


@vocab_app.command("review-sheet")
def vocab_review_sheet_cmd(
    packet: str = typer.Option(None, "--packet", help="e.g. E03-MS"),
    out: str = typer.Option(None, "--out", help="output directory"),
) -> None:
    """Generate the sheet a human reviews the vocabulary from, including the
    automated single-source cross-check for every derived fact."""
    from .vocab import review_sheet_main
    raise typer.Exit(review_sheet_main(packet=packet, out=out))


@app.command("preflight")
def preflight_cmd(
    stage: str = typer.Option(..., "--stage", help="stage name, e.g. pilot_manipulation"),
) -> None:
    """Run the pre-first-run checklist. Exits non-zero if any blocking item
    fails. Run it immediately before the first real episode."""
    from .preflight import run_preflight
    raise typer.Exit(run_preflight(stage))



def main() -> None:
    app()


if __name__ == "__main__":
    main()
