"""Stage 0 experiment sedition for the Briefing Integrity / AI Sedition Acts study."""

class HarnessError(Exception):
    """Base class for all sedition errors."""


class PrivacyLeakError(HarnessError):
    """Raised when private material is about to cross a model-facing boundary."""


class SpecViolationError(HarnessError):
    """Raised when an input artifact violates a locked structural invariant."""

