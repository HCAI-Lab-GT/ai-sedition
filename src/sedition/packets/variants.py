"""Runtime packet variants: control twins and report subsetting.

Two mechanisms, both of which change what the ANALYST reads and nothing else.

VOCABULARY (2026-08-27). The twins ARE the control condition; "ablated" was
the legacy machine identifier for it. The rename is forward-only: the 882
committed episodes and every .eval keep "ablated", archived twin files keep
their "-ablated.json" names, and `canonical_variant` below is the single seam
that maps the legacy spellings onto the current ones. Old identifiers stay
parseable forever.

CONTROL TWIN (PREREGISTRATION 18.4, 46). The same twelve reports with the
decisive elements resolved rather than removed, so the correct officer answer
becomes routine update. Populates the false-positive row, which is structurally
empty in every threat packet, and is therefore the test of whether the officer
reads the briefing at all.

REPORT SUBSETTING (PREREGISTRATION 42). The benign-error arm. One report is
removed so exactly one derived relation becomes unformable, while every atomic
constituent survives. The control arms drop an inert report of matched length so
report count and input volume are held constant across arms.

REPORT SUBSETTING IS CLOSED in this release -- SUBSET_TABLE and
CONTROL_SUBSET_TABLE are empty and `subset_packet` refuses with the reason.
The variant names stay in VARIANTS so that reopening the arm is a table edit
plus a re-derivation rather than a signature change, and so that a run asking
for one gets the closure message instead of an unknown-variant error.

WHY THIS RETURNS A REAL `Packet` RATHER THAN PATCHING THE RENDERER
------------------------------------------------------------------
`_reports_in_order` raises unless the permutation matches the packet's report
ids exactly, and `validate_rendered` asserts each report block appears exactly
once. Both guards exist because a silently dropped report has cost this project
a run before. Building an explicit reduced `Packet` keeps both guards in force
over the reduced set instead of weakening either -- see 42.7.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from sedition.packets.build import Packet, Report
from sedition.storage.paths import TWINS_DIR

#: Report-subsetting is not part of the released matrix. Reopening it would
#: require independently selecting and validating a report drop for each
#: packet and separately checking the control twins; it must not be inferred
#: from report numbers alone.
SUBSET_TABLE: dict[str, dict[str, str]] = {}

#: Subsetting applied to the CONTROL twin rather than the threat packet.
#: Closed with SUBSET_TABLE.
CONTROL_SUBSET_TABLE: dict[str, dict[str, str]] = {}

#: The variants a run may ask for, in the current vocabulary. Legacy spellings
#: ("ablated", "subset_control", ...) are accepted everywhere a variant enters
#: from outside and are mapped here by `canonical_variant`.
VARIANTS = ("threat", "control", "subset_benign", "subset_matched",
            "control_subset_resolution", "control_subset_inert")

#: Variants derived from a twin. These carry the twin's text, so the DRAFT gate
#: applies to them exactly as it applies to "control".
CONTROL_DERIVED = ("control", "control_subset_resolution", "control_subset_inert")


#: The single seam between the stored vocabulary and the live one. Keys are the
#: legacy machine identifiers exactly as written in committed episodes, .eval
#: files and command.txt lines; values are the current names. Nothing else may
#: hard-code this mapping -- see also sedition/config/paper_names.json.
_LEGACY_VARIANTS: dict[str, str] = {
    "ablated": "control",
    "ablated_subset_resolution": "control_subset_resolution",
    "ablated_subset_inert": "control_subset_inert",
    # A DIFFERENT concept from the control twin: the length-matched inert
    # removal in the (closed) report-subsetting arm.
    "subset_control": "subset_matched",
}


def canonical_variant(name: str) -> str:
    """The current spelling of a packet-variant identifier.

    SCHEMA TRANSITION, 2026-08-27. The twins ARE the control condition and
    "ablated" was the legacy machine identifier for it; "subset_control" (the
    length-matched inert removal, a different concept) became "subset_matched".
    Stored identifiers are immutable -- the 882 committed episodes and every
    .eval keep the legacy spellings -- so every EXTERNAL string (metadata read
    from a log, a record, or a CLI) is routed through this function, loads
    under its old name, and DISPLAYS under the new one. Unknown names pass
    through unchanged so this can never swallow a genuinely wrong variant.
    """
    return _LEGACY_VARIANTS.get(name, name)

_REPORT_FIELDS = (
    "report_id", "serial", "precedence", "dtg",
    "originator", "subject", "reported_status", "text",
)


def _rehash(reports: tuple[Report, ...]) -> str:
    """A variant is a different stimulus and must not carry its parent's hash."""
    return hashlib.sha256("\n\n".join(r.text for r in reports).encode("utf-8")).hexdigest()


#: Set by an operator once the criterion table has been signed off. Until then
#: every twin file carries `review.status` starting "DRAFT".
_DRAFT_PREFIX = "DRAFT"

#: Escape hatch for the tooling that has to read a DRAFT twin in order to
#: REVIEW it -- the criterion-table builder, the diff scripts. Scored runs never
#: set this.
ALLOW_DRAFT_TWINS = False


def _require_reviewed(packet_id: str, path, data) -> None:
    """Refuse to hand a DRAFT twin to a scored run.

    The twins carried `"status": "DRAFT - awaiting criterion-level human
    review"` and NOTHING read it. The marker was inert: `resolve_packet` loaded
    the file, the run started, and 54 episodes were scored against stimuli whose
    own metadata said they were not cleared. Documentation asserted a gate that
    did not exist, which is worse than having no gate -- the claim was used as
    the reason it was safe to proceed.

    `ALLOW_DRAFT_TWINS` exists because the review tooling must read the very
    files this blocks. It is never set by a run.
    """
    if ALLOW_DRAFT_TWINS or not isinstance(data, dict):
        return
    # Top-level "status" is the shape the twins actually use; "review.status"
    # is accepted too so a later nesting does not silently disable the gate.
    review = data.get("review")
    status = data.get("status", "")
    if not status and isinstance(review, dict):
        status = review.get("status", "")
    if not status:
        raise ValueError(
            f"{path}: no review status. A twin with no recorded review state "
            f"cannot be told apart from one that was never reviewed, so it is "
            f"refused rather than assumed cleared."
        )
    if str(status).strip().upper().startswith(_DRAFT_PREFIX):
        raise ValueError(
            f"{packet_id} is a DRAFT twin and must not be used in a scored run: "
            f"{status!r}. Sign off the criterion table "
            f"(docs/twins/CRITERION_TABLE_FOR_SIGNOFF.md), then set "
            f"status in {path.name}. Review tooling that must read a "
            f"draft sets variants.ALLOW_DRAFT_TWINS."
        )


@lru_cache(maxsize=16)
def control_packet(packet_id: str) -> Packet:
    """The drafted control twin for `packet_id`.

    Raises:
        FileNotFoundError: if no twin has been drafted. A missing twin must stop
            the run rather than silently fall back to the threat packet, which
            would file a control episode under a stimulus that answers NOTIFY.
    """
    path = TWINS_DIR / f"{packet_id}-control.json"
    if not path.exists():
        # Archived twins keep their legacy "-ablated.json" names.
        legacy = TWINS_DIR / f"{packet_id}-ablated.json"
        if legacy.exists():
            path = legacy
        else:
            available = sorted(
                p.name for pat in ("*-control.json", "*-ablated.json")
                for p in TWINS_DIR.glob(pat))
            raise FileNotFoundError(
                f"no control twin for {packet_id} at {path}; available: {available}"
            )
    data = json.loads(path.read_text(encoding="utf-8"))
    _require_reviewed(packet_id, path, data)
    rows = data["reports"] if isinstance(data, dict) else data
    reports = []
    for row in rows:
        missing = [f for f in _REPORT_FIELDS if f not in row]
        if missing:
            raise ValueError(f"{path}: report {row.get('report_id')} missing {missing}")
        reports.append(Report(**{f: row[f] for f in _REPORT_FIELDS}))
    event_id, version = packet_id.split("-", 1)
    return Packet(
        packet_id=packet_id,
        event_id=event_id,
        version=version,
        reports=tuple(reports),
        text_sha256=_rehash(tuple(reports)),
    )


def subset_packet(packet_id: str, role: str, *, base_variant: str = "threat") -> Packet:
    """`packet_id` with one report removed.

    Args:
        packet_id: an MS packet. SS packets carry one derived fact, so removing
            its carrier leaves nothing to measure (37.1) and subsetting them is
            refused rather than silently producing a degenerate cell. This is a
            property of the packets, not an untested gap: in every SS answer key
            the whole minimal criterion set is {R06}, so there is no report whose
            removal drops exactly one relation.
        role: on a threat packet, "benign" removes the decisive report and
            "control" an inert one of matched length. On a control twin,
            "resolution" removes the report carrying the resolution and "inert"
            one that carries none -- see CONTROL_SUBSET_TABLE.
        base_variant: "threat" or "control". Subsetting a twin is a different experiment from
            subsetting its parent and the two never pool.
    """
    from sedition_inspect._resources import packet as _threat

    base_variant = canonical_variant(base_variant)
    if base_variant == "control":
        table, allowed = CONTROL_SUBSET_TABLE, ("resolution", "inert")
    elif base_variant == "threat":
        table, allowed = SUBSET_TABLE, ("benign", "control")
    else:
        raise ValueError(f"subset base_variant must be threat or control, got {base_variant!r}")

    if role not in allowed:
        raise ValueError(
            f"subset role for base_variant={base_variant!r} must be one of "
            f"{allowed}, got {role!r}")
    if not table:
        raise ValueError(
            f"the subset/benign arm is CLOSED: {packet_id!r} variant "
            f"{role!r} (base_variant={base_variant!r}) cannot be built. The "
            f"release contains no reviewed per-packet subset definition. "
            f"Reopening this arm requires independently defining and validating "
            f"the report drops for every released packet."
        )
    if packet_id not in table:
        raise ValueError(
            f"no subset entry for {packet_id}; the table covers MS packets only "
            f"({', '.join(sorted(table))}). SS packets carry a single "
            f"derived fact, so subsetting them removes the whole measure."
        )
    drop = table[packet_id][role]
    base = control_packet(packet_id) if base_variant == "control" else _threat(packet_id)
    if drop not in base.report_ids:
        raise ValueError(f"{packet_id} has no report {drop}; the subset table is stale")
    reports = tuple(r for r in base.reports if r.report_id != drop)
    if len(reports) != len(base.reports) - 1:
        raise ValueError(f"{packet_id}: dropping {drop} removed {len(base.reports) - len(reports)}")
    return Packet(
        packet_id=packet_id,
        event_id=base.event_id,
        version=base.version,
        reports=reports,
        text_sha256=_rehash(reports),
    )


def variant_permutation(pk: Packet, permutation: tuple[str, ...]) -> tuple[str, ...]:
    """The block's permutation, restricted to the reports this variant kept.

    The dataset draws one permutation per block over the THREAT packet's twelve
    ids, and that shared draw is the matched-comparison guarantee. A subset
    packet has eleven, so the analyst's order is the same draw with the dropped
    id removed: relative order of every surviving report is unchanged across
    arms, and `_reports_in_order` still asserts an exact match over the reduced
    set (42.7). A twin keeps all twelve ids, so this is the identity for it.
    """
    kept = set(pk.report_ids)
    out = tuple(rid for rid in permutation if rid in kept)
    if sorted(out) != sorted(kept):
        raise ValueError(
            f"block permutation covers {sorted(set(permutation) & kept)} but the "
            f"{pk.packet_id} variant needs {sorted(kept)}")
    return out


def resolve_packet(packet_id: str, variant: str = "threat") -> Packet:
    """The packet a run should hand the analyst, for the declared variant.

    Legacy spellings ("ablated", "subset_control", ...) are canonicalized
    first, so a variant read from an old record or command line resolves to
    exactly the packet it always did.
    """
    from sedition_inspect._resources import packet as _threat

    variant = canonical_variant(variant)
    if variant == "threat":
        return _threat(packet_id)
    if variant == "control":
        return control_packet(packet_id)
    if variant == "subset_benign":
        return subset_packet(packet_id, "benign")
    if variant == "subset_matched":
        return subset_packet(packet_id, "control")
    if variant == "control_subset_resolution":
        return subset_packet(packet_id, "resolution", base_variant="control")
    if variant == "control_subset_inert":
        return subset_packet(packet_id, "inert", base_variant="control")
    raise ValueError(
        f"unknown packet variant {variant!r} - expected one of {', '.join(VARIANTS)}"
    )


# ---------------------------------------------------------------------------
# Back-compat aliases for the pre-2026-08-27 vocabulary. Importers of the old
# names keep working; new code uses the control_* spellings above.
ablated_packet = control_packet
ABLATED_DERIVED = CONTROL_DERIVED
ABLATED_SUBSET_TABLE = CONTROL_SUBSET_TABLE
