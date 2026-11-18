"""Prompt-component registry: versions and content fingerprints.

Known version skew (do not paper over): the attached overlays are v4 while
other specifications reference v5/v6 names. Components register with the
version their source text actually carries; assembling a call records every
component version+hash AND the hash of the full rendered prompt. Golden files
are created in M2, after the final shared analyst and overlay versions are
assembled — not from the current skewed set.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .. import HarnessError


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromptComponent:
    name: str            # e.g. "analyst_common"
    version: str         # human-readable, e.g. "v4" — from the source text itself
    text: str = field(repr=False)

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)

    @property
    def ref(self) -> dict[str, str]:
        """The form stored in call records."""
        return {"name": self.name, "version": self.version, "sha256": self.sha256}


@dataclass(frozen=True)
class RenderedPrompt:
    """A fully rendered prompt plus the provenance of every component in it."""
    role: str                                  # e.g. "analyst_briefing"
    text: str = field(repr=False)
    components: tuple[PromptComponent, ...] = ()

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)

class PromptRegistry:
    """Immutable-once-registered store of prompt components."""

    def __init__(self):
        self._components: dict[tuple[str, str], PromptComponent] = {}

    def register(self, component: PromptComponent) -> PromptComponent:
        key = (component.name, component.version)
        existing = self._components.get(key)
        if existing is not None:
            if existing.sha256 != component.sha256:
                raise HarnessError(
                    f"prompt {component.name} {component.version} re-registered with "
                    "different text — prompt changes require a NEW version"
                )
            return existing
        self._components[key] = component
        return component

    def get(self, name: str, version: str) -> PromptComponent:
        try:
            return self._components[(name, version)]
        except KeyError:
            raise HarnessError(f"prompt component {name} {version} not registered") from None
