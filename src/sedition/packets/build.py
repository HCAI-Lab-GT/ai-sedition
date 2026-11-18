"""Parse the three scenario packages into structured packets.

The scenario markdown files in docs/scenarios/ are READ-ONLY inputs. This
parser never mutates them; if the structure does not match the locked
expectations it raises SpecViolationError and names the mismatch.

Model-facing / key-side split, established at parse time:

  model-facing (per packet): scenario premise (§1), notification standard (§2),
      the 12 reports in canonical order.
  key-side only: the package header (it states the correct decision), §0
      "HOW THIS PACKAGE IS USED" (it explains the SS/MS manipulation), and
      Appendix A (ground truth / scoring key).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import SpecViolationError

#: This public release contains exactly E01-E03. Restricting the parser here
#: prevents an unreviewed scenario from entering a run merely by being copied
#: into a resource directory.
EVENT_ID_RE = r"E0[1-3]"
REPORT_ID_RE = re.compile(rf"^({EVENT_ID_RE})-(SS|MS)-R(0[1-9]|1[0-2])$")
PACKET_HEADER_RE = re.compile(rf"^PACKET ({EVENT_ID_RE}-(?:SS|MS)) — ")
APPENDIX_RE = re.compile(r"^APPENDIX A — GROUND TRUTH")
SECTION0_RE = re.compile(r"^0\. HOW THIS PACKAGE IS USED")
SECTION1_RE = re.compile(r"^1\. SCENARIO PREMISE")
SECTION2_RE = re.compile(r"^2\. NOTIFICATION STANDARD")
STATUS_RE = re.compile(r"^\d+\. STATUS\.\s*(.+)$", re.MULTILINE)

REPORTS_PER_PACKET = 12


@dataclass(frozen=True)
class Report:
    report_id: str
    serial: str
    precedence: str
    dtg: str
    originator: str          # FROM:
    subject: str             # SUBJ:
    reported_status: str     # the "n. STATUS." paragraph
    text: str                # exact source text of the report block


@dataclass(frozen=True)
class Packet:
    packet_id: str           # e.g. "E01-SS"
    event_id: str            # "E01"
    version: str             # "SS" | "MS"
    reports: tuple[Report, ...]
    text_sha256: str         # hash of the exact packet text span

    @property
    def report_ids(self) -> tuple[str, ...]:
        return tuple(r.report_id for r in self.reports)


@dataclass(frozen=True)
class ScenarioPackage:
    event_id: str
    source_path: Path
    source_sha256: str
    scenario_premise: str            # §1, model-facing
    premise_subsections: dict[str, str]   # "1.1" -> text, for slot selection at assembly
    notification_standard: str       # §2, model-facing
    packets: dict[str, Packet]       # "E01-SS", "E01-MS"
    design_notes: str = field(repr=False, default="")   # §0 — KEY-SIDE ONLY
    package_header: str = field(repr=False, default="") # title lines — KEY-SIDE ONLY
    appendix_a: str = field(repr=False, default="")     # ground truth — KEY-SIDE ONLY


def _line_index(lines: list[str], pattern: re.Pattern, path: Path) -> int:
    for i, line in enumerate(lines):
        if pattern.match(line):
            return i
    raise SpecViolationError(f"{path.name}: no line matches {pattern.pattern!r}")


def _parse_header_field(block: str, key: str, report_id: str, path: Path) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", block, re.MULTILINE)
    if not m:
        raise SpecViolationError(f"{path.name}: report {report_id} missing {key}: field")
    return m.group(1).strip()


def _parse_packet(packet_id: str, text: str, path: Path) -> Packet:
    event_id, version = packet_id.split("-")
    lines = text.splitlines()

    # Report blocks start at a standalone report-ID line whose OWN header
    # follows. The confirming line used to be the UNCLASSIFIED//EXERCISE//
    # FICTIONAL banner, which made the exercise framing structural: the
    # de-fictionalised materials could not be parsed at all, so they sat
    # unused while every run shipped the banners to the analyst.
    #
    # Anchoring on "REPORT ID:" instead uses the report's own identity, which
    # both versions carry. Banner-bearing files still parse — the banner sits
    # between the two lines and is skipped — so this is backwards compatible
    # and the drift test covers both.
    starts = [i for i, line in enumerate(lines)
              if REPORT_ID_RE.match(line.strip())
              and any(lines[j].strip().startswith("REPORT ID:")
                      for j in range(i + 1, min(i + 4, len(lines))))]
    if len(starts) != REPORTS_PER_PACKET:
        raise SpecViolationError(
            f"{path.name}: packet {packet_id} has {len(starts)} report blocks, "
            f"expected exactly {REPORTS_PER_PACKET}"
        )

    reports: list[Report] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end]).rstrip()
        heading_id = lines[start].strip()

        expected_id = f"{packet_id}-R{n + 1:02d}"
        if heading_id != expected_id:
            raise SpecViolationError(
                f"{path.name}: packet {packet_id} report {n + 1} has id {heading_id}, "
                f"expected {expected_id} (report IDs are permanent and sequential)"
            )
        field_id = _parse_header_field(block, "REPORT ID", heading_id, path)
        if field_id != heading_id:
            raise SpecViolationError(
                f"{path.name}: report {heading_id} REPORT ID field says {field_id}"
            )
        status_m = STATUS_RE.search(block)
        if not status_m:
            raise SpecViolationError(f"{path.name}: report {heading_id} has no STATUS paragraph")

        reports.append(Report(
            report_id=heading_id,
            serial=_parse_header_field(block, "SERIAL", heading_id, path),
            precedence=_parse_header_field(block, "PRECEDENCE", heading_id, path),
            dtg=_parse_header_field(block, "DTG", heading_id, path),
            originator=_parse_header_field(block, "FROM", heading_id, path),
            subject=_parse_header_field(block, "SUBJ", heading_id, path),
            reported_status=status_m.group(1).strip(),
            text=block,
        ))

    return Packet(
        packet_id=packet_id,
        event_id=event_id,
        version=version,
        reports=tuple(reports),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def parse_scenario_file(path: str | Path) -> ScenarioPackage:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.splitlines()

    i_s0 = _line_index(lines, SECTION0_RE, path)
    i_s1 = _line_index(lines, SECTION1_RE, path)
    i_s2 = _line_index(lines, SECTION2_RE, path)
    packet_lines = [(i, PACKET_HEADER_RE.match(line).group(1))
                    for i, line in enumerate(lines) if PACKET_HEADER_RE.match(line)]
    i_app = _line_index(lines, APPENDIX_RE, path)
    if len(packet_lines) != 2:
        raise SpecViolationError(f"{path.name}: expected 2 PACKET sections, found {len(packet_lines)}")
    if not (i_s0 < i_s1 < i_s2 < packet_lines[0][0] < packet_lines[1][0] < i_app):
        raise SpecViolationError(f"{path.name}: sections out of expected order")

    premise = "\n".join(lines[i_s1 + 1:i_s2]).strip()
    subsections: dict[str, str] = {}
    current_key, current_buf = None, []
    for line in premise.splitlines():
        m = re.match(r"^(1\.\d+)\s", line)
        if m:
            if current_key:
                subsections[current_key] = "\n".join(current_buf).strip()
            current_key, current_buf = m.group(1), [line]
        elif current_key:
            current_buf.append(line)
    if current_key:
        subsections[current_key] = "\n".join(current_buf).strip()

    (i_p1, id_p1), (i_p2, id_p2) = packet_lines
    packets = {
        id_p1: _parse_packet(id_p1, "\n".join(lines[i_p1:i_p2]), path),
        id_p2: _parse_packet(id_p2, "\n".join(lines[i_p2:i_app]), path),
    }

    event_ids = {p.event_id for p in packets.values()}
    if len(event_ids) != 1:
        raise SpecViolationError(f"{path.name}: packets belong to different events: {event_ids}")
    event_id = event_ids.pop()
    versions = [p.version for p in packets.values()]
    # A scenario carries exactly one SS and one MS packet; that pairing is the
    # source-form manipulation. A multiset check catches a file with two copies
    # of one form.
    if sorted(versions) != ["MS", "SS"]:
        raise SpecViolationError(
            f"{path.name}: expected exactly one SS and one MS packet, got {sorted(versions)}")

    return ScenarioPackage(
        event_id=event_id,
        source_path=path,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        scenario_premise=premise,
        premise_subsections=subsections,
        notification_standard="\n".join(lines[i_s2 + 1:i_p1]).strip(),
        packets=packets,
        design_notes="\n".join(lines[i_s0 + 1:i_s1]).strip(),
        package_header="\n".join(lines[:i_s0]).strip(),
        appendix_a="\n".join(lines[i_app:]).strip(),
    )


#: The complete runnable set. A directory that does not contain exactly these
#: three scenario packages is malformed and is refused.
CORE_EVENTS: tuple[str, ...] = ("E01", "E02", "E03")

#: No additional scenarios are distributed or runnable in this artifact.
#: These empty registries retain the parser API while making every
#: `--admit-heldout` request fail closed.
HELDOUT_RUNNABLE: frozenset[str] = frozenset()
HELDOUT_VOID: dict[str, str] = {}
HELDOUT_RETIRED: dict[str, str] = {}
HELDOUT_RENAMED: dict[str, str] = {}

def parse_all(
    scenario_dir: str | Path,
    *,
    admit_heldout: tuple[str, ...] = (),
    heldout_dir: str | Path | None = None,
) -> dict[str, ScenarioPackage]:
    """Parse every scenario package in the directory, keyed by event id.

    The check is NOT that the set is small; it is that the set is EXACTLY what
    the caller declared. A directory carrying an unknown event, a duplicate, or
    a missing core event is malformed and is refused either way.

    Args:
        admit_heldout: held-out event ids this call is allowed to load, from
            HELDOUT_RUNNABLE. Opt-in per call rather than a global widening,
            because the reason this guard exists is to keep VOID packets out of
            reach of a default run -- see HELDOUT_VOID. Passing a void id is
            refused by name with its baseline, not silently allowed.
        heldout_dir: where held-out packages live. Defaults to the installed
            package's held-out resource directory.
    """
    scenario_dir = Path(scenario_dir)
    packages: dict[str, ScenarioPackage] = {}
    for path in sorted(scenario_dir.glob("*.md")):
        pkg = parse_scenario_file(path)
        if pkg.event_id in packages:
            raise SpecViolationError(f"duplicate event id {pkg.event_id}")
        packages[pkg.event_id] = pkg
    if sorted(packages) != list(CORE_EVENTS):
        raise SpecViolationError(
            f"expected events {', '.join(CORE_EVENTS)}; found {sorted(packages)}")

    for ev in admit_heldout:
        if ev in HELDOUT_RENAMED:
            raise SpecViolationError(
                f"{ev} is not held out any more: it was renamed on disk to "
                f"{HELDOUT_RENAMED[ev]} on 2026-08-26 and is now a CORE "
                f"event, loaded by default from docs/scenarios/. Drop the "
                f"--admit-heldout flag and name {HELDOUT_RENAMED[ev]} "
                f"directly. Episodes already collected still carry {ev} "
                f"packet ids; the source is renamed, the collected data "
                f"is not.")
        if ev in HELDOUT_RETIRED:
            raise SpecViolationError(
                f"{ev} is RETIRED and may not be admitted to a run: "
                f"{HELDOUT_RETIRED[ev]}")
        if ev in HELDOUT_VOID:
            raise SpecViolationError(
                f"{ev} is VOID and may not be admitted to a run: "
                f"{HELDOUT_VOID[ev]}. Its saboteur figures are not quotable "
                f"because the baseline they sit on is broken.")
        if ev not in HELDOUT_RUNNABLE:
            raise SpecViolationError(
                f"unknown held-out event {ev!r}; admissible: "
                f"{', '.join(sorted(HELDOUT_RUNNABLE))}")
        if heldout_dir is None:
            from sedition.storage.paths import HELDOUT_SCENARIOS_DIR

            hd = HELDOUT_SCENARIOS_DIR
        else:
            hd = Path(heldout_dir)
        hits = [f for f in sorted(hd.glob("*.md"))
                if parse_scenario_file(f).event_id == ev]
        if not hits:
            raise SpecViolationError(f"{ev} admitted but no package found under {hd}")
        packages[ev] = parse_scenario_file(hits[0])
    return packages


def parse_all_including_heldout(scenarios_dir, heldout_dir=None):
    """Validation-only parser for an optional external scenario directory.

    This release supplies no held-out directory, so normal execution
    returns exactly the three core packages. Keeping this path separate avoids
    widening the runtime set if a developer supplies external materials while
    authoring a future extension.
    """
    from pathlib import Path

    pkgs = dict(parse_all(scenarios_dir))
    if heldout_dir is None:
        from sedition.storage.paths import HELDOUT_SCENARIOS_DIR

        heldout = HELDOUT_SCENARIOS_DIR
    else:
        heldout = Path(heldout_dir)
    if heldout.exists():
        for f in sorted(heldout.glob("*.md")):
            pkg = parse_scenario_file(f)
            pkgs[pkg.event_id] = pkg
    return pkgs
