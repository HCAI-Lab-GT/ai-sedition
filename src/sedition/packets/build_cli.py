"""`sedition build-packets` — parse the scenario markdown into
build/packets.json (model-facing content + hashes).

Appendix A and other key-side material are NOT written here; they belong to
the answer key.
"""
from __future__ import annotations

import json

from ..storage.paths import (
    BUILD_DIR,
    BUILT_PACKETS_JSON,
    PACKAGE_ROOT,
    REPO_ROOT,
    SCENARIOS_DIR,
)
from .build import parse_all


def main() -> int:
    packages = parse_all(SCENARIOS_DIR)
    out = {}
    for event_id, pkg in sorted(packages.items()):
        out[event_id] = {
            "source_file": str(pkg.source_path.relative_to(PACKAGE_ROOT)),
            "source_sha256": pkg.source_sha256,
            "scenario_premise_subsections": pkg.premise_subsections,
            "notification_standard": pkg.notification_standard,
            "packets": {
                pid: {
                    "packet_sha256": p.text_sha256,
                    "reports": [
                        {
                            "report_id": r.report_id,
                            "serial": r.serial,
                            "precedence": r.precedence,
                            "dtg": r.dtg,
                            "originator": r.originator,
                            "subject": r.subject,
                            "reported_status": r.reported_status,
                            "text": r.text,
                        }
                        for r in p.reports
                    ],
                }
                for pid, p in sorted(pkg.packets.items())
            },
        }
    BUILD_DIR.mkdir(exist_ok=True)
    BUILT_PACKETS_JSON.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for _event_id, pkg in sorted(packages.items()):
        for pid, p in sorted(pkg.packets.items()):
            print(f"{pid}: {len(p.reports)} reports, sha256 {p.text_sha256[:12]}")
    print(f"wrote {BUILT_PACKETS_JSON.relative_to(REPO_ROOT)}")
    return 0
