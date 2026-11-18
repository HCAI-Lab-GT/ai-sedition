"""What a run ACTUALLY did, derived from the run.

Written because a declaration was caught lying. `scorers.py` recorded
`{"method": "lexical-overlap-v1"}` as a hardcoded string literal while
`score_facts` had already defaulted to `anchor-relation-v2`, so every episode
in run-llama-01 carried correct v2 scores under the wrong name. Nothing
detected it, because a constant cannot disagree with itself.

The rule this module follows: **nothing here is declared, everything is
observed.** Every field is read back out of the completed log — the model
strings the calls were actually made against, the scorer name the results
actually carry, the flags that actually fired. A field that cannot be
observed is reported as unknown rather than assumed, which is the whole point.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class RoleBinding:
    role: str
    model: str
    calls: int

    @property
    def provider(self) -> str:
        return self.model.split("/", 1)[0]

    @property
    def deployment(self) -> str:
        return self.model.split("/", 1)[1] if "/" in self.model else self.model


@dataclass
class RunProvenance:
    roles: list[RoleBinding] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    scoring_methods: list[str] = field(default_factory=list)
    episodes: int = 0
    valid: int = 0
    #: Episodes whose analyst emitted reasoning that had to be stripped.
    think_episodes: int = 0
    think_unclosed: int = 0
    #: Episodes where AnalystPrivate.reasoning is non-empty — the direct
    #: evidence that stripping ran and routed something, independent of flags.
    reasoning_captured: int = 0
    officer_think: int = 0
    officer_prose: int = 0
    monitor_invalid: int = 0
    drs_scored: int = 0

    @property
    def think_stripping_evidence(self) -> str:
        """Deliberately not a bool.

        Zero observations is ambiguous: it means either the stripping never
        ran or no model chose to think. The log cannot tell those apart, so
        this says which of the two the numbers support rather than picking.
        """
        if self.reasoning_captured or self.think_episodes:
            return (f"ACTIVE — reasoning stripped and stored on "
                    f"{self.reasoning_captured}/{self.episodes} episodes")
        return ("NO EVIDENCE — no episode carried reasoning. Cannot "
                "distinguish 'stripping inactive' from 'model never thought'")

    def lines(self) -> list[str]:
        out = ["PROVENANCE (read from the run, not declared)"]
        for b in self.roles:
            out.append(f"  {b.role:14s} {b.provider}/{b.deployment}  ({b.calls} calls)")
        out.append(f"  providers      {', '.join(self.providers) or 'none'}")
        out.append(f"  fact scorer    {', '.join(self.scoring_methods) or 'unknown'}")
        out.append(f"  think strip    {self.think_stripping_evidence}")
        if self.think_unclosed:
            out.append(f"                 {self.think_unclosed} truncated mid-reasoning")
        out.append(f"  officer        reasoning on {self.officer_think}, "
                   f"prose-wrapped JSON on {self.officer_prose} of {self.episodes}")
        out.append(f"  DRS coverage   {self.drs_scored}/{self.episodes} scored, "
                   f"{self.monitor_invalid} monitor outputs rejected")
        return out


def run_provenance(log) -> RunProvenance:
    """Derive provenance from a completed `EvalLog`."""
    p = RunProvenance()
    samples = log.samples or []
    p.episodes = len(samples)

    per_role: Counter = Counter()
    role_model: dict[str, str] = {}
    methods: set[str] = set()

    for s in samples:
        st = s.store
        flags = set(st.get("EpisodePublic:flags") or [])
        if not st.get("EpisodePublic:invalid"):
            p.valid += 1
        if "THINK_STRIPPED" in flags:
            p.think_episodes += 1
        if "THINK_UNCLOSED" in flags:
            p.think_unclosed += 1
        if "WO_THINK_STRIPPED" in flags:
            p.officer_think += 1
        if "WO_PROSE_PREFIX" in flags:
            p.officer_prose += 1
        if (st.get("AnalystPrivate:reasoning") or "").strip():
            p.reasoning_captured += 1

        for ev in s.events:
            if ev.event == "model" and getattr(ev, "role", None):
                per_role[(ev.role, ev.model)] += 1
                role_model[ev.role] = ev.model

        drs = s.scores.get("monitor_drs") if s.scores else None
        if drs is not None:
            if (drs.metadata or {}).get("monitor_invalid"):
                p.monitor_invalid += 1
            if isinstance(drs.value, (int, float)):
                p.drs_scored += 1
        for name in ("atomic_facts", "derived_facts"):
            sc = s.scores.get(name) if s.scores else None
            if sc is not None:
                m = (sc.metadata or {}).get("method")
                if m:
                    methods.add(m)

    p.roles = [RoleBinding(role=r, model=m, calls=n)
               for (r, m), n in sorted(per_role.items())]
    p.providers = sorted({b.provider for b in p.roles})
    p.scoring_methods = sorted(methods)
    return p
