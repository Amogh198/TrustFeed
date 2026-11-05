from __future__ import annotations


class MediaInputError(Exception):
    """The submitted file cannot be analyzed. The message is safe to show users."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ClassifierUnavailable(Exception):
    """The classifier cannot produce a result. The message is safe to show users."""


class HashIndexUnavailable(Exception):
    """The pHash reference index cannot be used. The message is safe to show users."""
