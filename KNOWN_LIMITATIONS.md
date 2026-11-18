# Known limitations

These limitations are reported by the verification suite. They concern the
monitor's inputs and static packet checks. Documenting them does not change
the saved results; it does affect how those results should be interpreted.

## Scoring anchors visible to the monitor

Anchors are exact identifiers or phrases used by the mechanical fact scorer
to recognize a fact in a briefing. The monitor receives fact descriptions
alongside the reports and briefing. Although the renderer hides the dedicated
`anchors` and `scoring_note` fields, some descriptions repeat anchor strings.
For example, the E01 cell-life description includes `KRC-2`, which is also
a scorer anchor.

Six strict expected failures document this overlap. It can cue the monitor
about specific evidence to check, so the monitor is not evaluating from the
reports and briefing alone. The checks demonstrate exposure, not the size or
direction of any effect on DRS. Establishing that effect would require a
separate comparison with neutralized descriptions. This finding does not by
itself demonstrate leakage to the analyst or officer, or incorrect mechanical
scores.

The released descriptions and prompts remain unchanged so the saved results
retain their actual measurement configuration.

## Control-gate blindness on two inference-linked MS packets

Three strict expected failures cover a limitation of the static control gate.
The gate asks whether a decisive relationship can be formed directly from
packet text. For two MS packets, the governing relationship requires a
consequence inference and is not stated verbatim, so the static gate cannot
distinguish the unresolved threat from its resolved control using that check
alone.

## Vocabulary warnings

`sedition build-key` emits six warnings:

- Three importance-signalling warnings arise because “key” is a domain noun in
  E01 rather than an importance cue.
- Three derived-count warnings report that MS and SS each carry one registered
  derived fact. The MS manipulation changes distribution across sources rather
  than the number of registered derived facts.

## Scope

The saved 480-row matrix is unchanged. This is not evidence that the monitor
input overlap has no effect. Interpret DRS as measured with the supplied fact
vocabulary, and assess the control packets using their authored evidence and
criteria as well as the static gate.
