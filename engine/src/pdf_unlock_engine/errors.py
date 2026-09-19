"""Errors the engine raises. Every one carries a message safe to print."""


class PdfUnlockError(Exception):
    """Base class for everything this package raises."""


class NotAPdfError(PdfUnlockError):
    """The file is missing, unreadable, or not a PDF at all."""


class NotEncryptedError(PdfUnlockError):
    """The PDF has no encryption, so there is nothing to remove."""


class WrongPasswordError(PdfUnlockError):
    """A password was supplied and the PDF rejected it."""


class NoPasswordFoundError(PdfUnlockError):
    """No password was supplied and none of the known candidates worked."""

    def __init__(self, message: str, tried: int = 0) -> None:
        super().__init__(message)
        self.tried = tried


class OutputExistsError(PdfUnlockError):
    """The destination already exists and overwriting was not requested."""


class ConfigError(PdfUnlockError):
    """The config file is malformed or holds a value we cannot use."""


class SecretsError(PdfUnlockError):
    """The OS keyring could not be reached."""
