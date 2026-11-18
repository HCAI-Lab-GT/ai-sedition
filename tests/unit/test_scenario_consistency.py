"""Integrity checks on the scenario files a model actually reads.

There used to be two copies of every scenario: the live one under
docs/scenarios/ and a de-fictionalised reference copy at the repo root, with a
test asserting they differed only in the exercise framing. That test earned
its keep twice — it caught "Nine reports each carry one indicator" being
reintroduced as "Ten" a month after the correction, and E01-MS-R04's SUBJ line
naming a camera its body never mentions.

The materials freeze wired the reference copies in as the live materials, so
the two copies became byte-identical and the root ones were removed. Keeping a
duplicate purely so a test can compare it against the original is guarding
against a failure mode the duplicate itself creates.

A scenario edit is still caught, three ways over, verified by mutating a
scenario and watching each one fail:

  * `validate-key --check-hashes` — source file hash mismatch, packet hash
    mismatch
  * `render-golden --check` — drift in every affected golden
  * the golden-comparison tests in inspect_port/

The SUBJ check below is the part that was never redundant: it tests a property
of the live copy on its own terms rather than against a second copy.
"""
from __future__ import annotations

import re

import pytest

from sedition.storage.paths import SCENARIOS_DIR

#: Any finding these lints surface is a defect in the released materials,
#: to be fixed in the packet -- not
#: a test to be relaxed. Both are about what a model reads: a SUBJ line naming
#: an identifier absent from its own body shows the analyst a discrepancy the
#: scenario did not intend, and an exercise marker in model-facing text tells
#: it the whole thing is fiction.
SCENARIOS = [
    SCENARIOS_DIR / "E01-amber-reach-retention-cell.md",
    SCENARIOS_DIR / "E02-marisol-sandpiper.md",
    SCENARIOS_DIR / "E03-hollis-restraint.md",
]


@pytest.mark.parametrize("live_name", SCENARIOS)
def test_no_report_subject_names_an_identifier_its_body_never_mentions(live_name):
    """The BR4-C2 defect, generalised.

    SUBJ lines are model-facing. A subject naming an identifier that appears
    nowhere in the body shows the analyst a discrepancy the scenario did not
    intend, which is indistinguishable from planted evidence.
    """
    text = live_name.read_text(encoding="utf-8")
    ident = re.compile(r"\b[A-Z]{1,4}\d{0,2}-[A-Z]?\d{1,4}\b")

    blocks = re.split(r"^(?=E0\d-(?:SS|MS)-R\d\d$)", text, flags=re.M)
    offenders = []
    for block in blocks:
        m = re.search(r"^SUBJ:\s*(.+)$", block, re.M)
        if not m:
            continue
        rid = block.splitlines()[0].strip()
        body = block[m.end():]
        for tok in set(ident.findall(m.group(1))):
            if tok not in body:
                offenders.append(f"{rid}: SUBJ names {tok!r}, absent from the body")

    assert not offenders, (
        f"{live_name}: subject line names an identifier the report never uses.\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("live_name", SCENARIOS)
def test_nothing_a_model_reads_mentions_an_exercise(live_name):
    """The materials freeze, held in place.

    The banner and the FICTIONAL MATERIAL disclaimer were removed so the
    analyst is not told it is being evaluated. Re-adding either would change
    what the experiment measures without changing a single prompt.
    """
    text = live_name.read_text(encoding="utf-8")
    for marker in ("FICTIONAL", "EXERCISE", "fictional"):
        assert marker not in text, (
            f"{live_name} reintroduces {marker!r}. The materials are frozen: "
            f"nothing a model reads may disclose that this is an evaluation."
        )
