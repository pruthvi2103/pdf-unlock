"""The part that actually removes the password.

This is deliberately the smallest module in the package. pikepdf wraps qpdf,
which knows every revision of the PDF standard security handler banks use, so
"remove the encryption" is really just "open it, then save it without any".

The source file is never modified. Output is written atomically and chmod 600,
because a decrypted bank statement deserves at least that much.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from .errors import NotAPdfError, NotEncryptedError, OutputExistsError, WrongPasswordError
from .inspect import PdfInfo, inspect_pdf

__all__ = [
    "UnlockResult",
    "unlock_pdf",
    "verify_password",
    "find_password",
    "output_path_for",
]


@dataclass(frozen=True)
class UnlockResult:
    source: Path
    output: Path
    password_source: str
    """Where the working password came from -- never the password itself."""
    encryption: str | None = None
    page_count: int | None = None
    restrictions_only: bool = False


def verify_password(path: str | Path, password: str) -> bool:
    """True when ``password`` opens this PDF."""
    import pikepdf

    try:
        with pikepdf.open(Path(path).expanduser(), password=password):
            return True
    except pikepdf.PasswordError:
        return False


def find_password(path: str | Path, candidates) -> tuple[str, str] | None:
    """Try candidates in order; return the first ``(password, source)`` that opens it.

    ``candidates`` is any iterable of ``(password, source)`` pairs. Trying a
    handful of your own passwords costs milliseconds, which is why the CLI can
    usually skip family matching entirely and just work.
    """
    seen: set[str] = set()
    for password, source in candidates:
        if password is None or password in seen:
            continue
        seen.add(password)
        if verify_password(path, password):
            return password, source
    return None


def output_path_for(
    source: Path,
    out_dir: Path,
    suffix: str = "",
    overwrite: bool = True,
) -> Path:
    """Where the unlocked copy should go, refusing to clobber the source."""
    source = Path(source).expanduser().resolve()
    out_dir = Path(out_dir).expanduser()
    dest = out_dir / f"{source.stem}{suffix}.pdf"

    if Path(os.path.abspath(dest)) == source:
        raise OutputExistsError(
            f"that would write over the encrypted original at {source}. "
            "Pick a different output directory, or set a suffix."
        )
    if dest.exists() and not overwrite:
        raise OutputExistsError(
            f"{dest} already exists. Pass --overwrite, or set overwrite = true in your config."
        )
    return dest


def unlock_pdf(
    source: str | Path,
    dest: str | Path,
    password: str = "",
    *,
    password_source: str = "explicit",
    overwrite: bool = True,
    info: PdfInfo | None = None,
) -> UnlockResult:
    """Write a password-free copy of ``source`` to ``dest``.

    Raises NotEncryptedError when there was nothing to remove, so the caller can
    say so plainly rather than silently producing a pointless copy.
    """
    import pikepdf

    source = Path(source).expanduser()
    dest = Path(dest).expanduser()
    info = info or inspect_pdf(source)

    if not info.encrypted:
        raise NotEncryptedError(f"{source.name} is not encrypted -- nothing to unlock.")
    if dest.exists() and not overwrite:
        raise OutputExistsError(f"{dest} already exists. Pass --overwrite to replace it.")

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")

    try:
        with pikepdf.open(source, password=password) as pdf:
            pages = len(pdf.pages)
            encryption = info.encryption or _revision_name(pdf)
            # linearize keeps the output friendly to streaming readers; encryption=False
            # is the whole point of this function.
            pdf.save(tmp, encryption=False)
        os.chmod(tmp, 0o600)
        tmp.replace(dest)
    except pikepdf.PasswordError as exc:
        _cleanup(tmp)
        raise WrongPasswordError(f"{source.name} rejected that password.") from exc
    except pikepdf.PdfError as exc:
        _cleanup(tmp)
        raise NotAPdfError(f"could not read {source.name}: {exc}") from exc
    except Exception:
        _cleanup(tmp)
        raise

    return UnlockResult(
        source=source,
        output=dest,
        password_source=password_source,
        encryption=encryption,
        page_count=pages,
        restrictions_only=info.restrictions_only,
    )


def _revision_name(pdf) -> str | None:
    from .inspect import _describe_encryption

    return _describe_encryption(pdf)


def _cleanup(tmp: Path) -> None:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
