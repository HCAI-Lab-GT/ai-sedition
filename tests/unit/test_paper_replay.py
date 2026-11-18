"""Exercise the hosted replay through task construction, stopping at model dispatch."""
import gzip
import json
import sys

from scripts import replay_paper, run_two_axis


def test_replay_dispatches_archived_inputs_and_caps(monkeypatch, tmp_path):
    manifest = json.loads(replay_paper.MANIFEST.read_text())
    with gzip.open(replay_paper.ROOT / manifest["dataset"]["file"]) as f:
        records = json.load(f)["episodes"]
    expected = {
        (r["packet_id"], r["block_index"], r["packet_variant"], r["cell"]): r
        for r in records
    }
    seen = set()
    phases = []

    def inspect_dispatch(*, tasks, metadata, **kwargs):
        assert phases == ["preflight", "preflight", "live"] or phases == [
            "preflight", "preflight", "live", "live"
        ]
        for sample in tasks[0].dataset:
            md = sample.metadata
            key = (md["packet_id"], md["block_index"], md["packet_variant"], md["cell"])
            assert key not in seen
            seen.add(key)
            assert md["permutation"] == expected[key]["permutation"]
            assert md["permutation_sha256"] == expected[key]["permutation_sha256"]
            cap = 8000 if md["event_id"] == "E02" else 10000
            assert metadata["token_budgets"]["briefing_max_tokens"] == cap
        return True, []

    def run_child(cmd):
        # The CLI uses separate interpreters so per-group solver overrides are local.
        with monkeypatch.context() as m:
            m.setattr(sys, "argv", cmd[1:])
            m.setattr(run_two_axis.task_mod, "sedition_episode", run_two_axis.task_mod.sedition_episode)
            m.setattr(run_two_axis.caps, "CAPABILITIES", dict(run_two_axis.caps.CAPABILITIES))
            phases.append("preflight" if "--check-provider" in cmd else "live")
            return run_two_axis.main()

    monkeypatch.setattr(replay_paper.subprocess, "call", run_child)
    monkeypatch.setattr(run_two_axis, "eval_set", inspect_dispatch)
    monkeypatch.setattr(run_two_axis, "build_model_roles", lambda *a, **kw: {"analyst": object()})
    monkeypatch.setattr(run_two_axis, "missing_env", lambda *a: [])
    monkeypatch.setattr(run_two_axis, "log_integrity_findings", lambda *a, **kw: [])
    monkeypatch.setattr(sys, "argv", ["replay_paper.py", "--run", "--log-root", str(tmp_path)])
    assert replay_paper.main() == 0
    assert seen == expected.keys()
    assert len(seen) == 480
