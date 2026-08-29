"""Public exception types used by NAMD Launcher.

The hierarchy mirrors ``interfaceforge.errors`` so callers that already handle
one can handle the other.
"""

from __future__ import annotations


class NamdLauncherError(RuntimeError):
    """Base error for an actionable workflow failure."""


class ConfigurationError(NamdLauncherError):
    """Raised when a campaign or scheduler profile is invalid."""


class SafetyError(NamdLauncherError):
    """Raised when an operation would overwrite or mutate unsafe state."""


class DependencyError(NamdLauncherError):
    """Raised when an optional runtime dependency is required but missing."""
