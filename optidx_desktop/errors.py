"""Typed failures shared by the worker, storage and UI.

Callers branch on these types instead of matching message text, so wording can
change without altering what is rolled back, retried or protected.
"""


class CorruptRecord(ValueError):
    """A strict JSON record exists but cannot be read; it is kept as evidence."""


class ManualRecoveryRequired(RuntimeError):
    """Automatic rollback failed; retained snapshots must be inspected."""


class GameBusy(RuntimeError):
    """Another OptiDX process holds this game's operation lock."""
