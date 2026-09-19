"""Read what a PDF will tell us before we have its password.

An encrypted PDF hides its metadata, so for locked files almost the only signal
available is the filename. That is why family matching leans on filename rules
and treats metadata as a bonus.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import NotAPdfError


@dataclass(frozen=True)
class PdfInfo:
    """What we could learn about a PDF without unlocking it."""

    path: Path
    encrypted: bool
    needs_password: bool
    """True when a user password is required just to open the file."""
    encryption: str | None = None
    """Human-readable algorithm, e.g. "AES-256". None when we cannot see it."""
    producer: str | None = None
    author: str | None = None
    title: str | None = None
    page_count: int | None = None

    @property
    def restrictions_only(self) -> bool:
        """Opens freely but carries an owner password limiting print/copy."""
        return self.encrypted and not self.needs_password


# qpdf reports the standard security handler's revision; that is what names the algorithm.
_BY_REVISION = {2: "RC4-40", 3: "RC4-128", 4: "AES-128", 5: "AES-256", 6: "AES-256"}


def _describe_encryption(pdf) -> str | None:
    """Name the algorithm, or None for a PDF that carries no encryption at all."""
    if not pdf.is_encrypted:
        return None
    try:
        revision = pdf.encryption.R
    except Exception:
        # An unencrypted PDF still yields an EncryptionInfo, and reading .R off it
        # raises KeyError rather than AttributeError.
        return None
    return _BY_REVISION.get(revision, f"R{revision}")


def inspect_pdf(path: str | Path) -> PdfInfo:
    """Describe a PDF's encryption state. Never raises on a merely locked file."""
    import pikepdf

    path = Path(path).expanduser()
    if not path.is_file():
        raise NotAPdfError(f"no such file: {path}")

    try:
        with pikepdf.open(path) as pdf:
            meta = pdf.docinfo
            return PdfInfo(
                path=path,
                encrypted=pdf.is_encrypted,
                needs_password=False,
                encryption=_describe_encryption(pdf),
                producer=_docinfo(meta, "/Producer"),
                author=_docinfo(meta, "/Author"),
                title=_docinfo(meta, "/Title"),
                page_count=len(pdf.pages),
            )
    except pikepdf.PasswordError:
        return PdfInfo(path=path, encrypted=True, needs_password=True)
    except pikepdf.PdfError as exc:
        raise NotAPdfError(f"not a readable PDF: {path} ({exc})") from exc


def _docinfo(meta, key: str) -> str | None:
    try:
        value = meta.get(key)
    except Exception:
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None
