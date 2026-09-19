"""Small terminal output helpers. No dependencies, so startup stays quick."""

from __future__ import annotations

import os
import sys

_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ENABLED else text


def bold(text: str) -> str:
    return _paint("1", text)


def dim(text: str) -> str:
    return _paint("2", text)


def green(text: str) -> str:
    return _paint("32", text)


def yellow(text: str) -> str:
    return _paint("33", text)


def red(text: str) -> str:
    return _paint("31", text)


def cyan(text: str) -> str:
    return _paint("36", text)


def ok(message: str) -> None:
    print(f"{green('✓')} {message}")


def info(message: str) -> None:
    print(f"{dim('·')} {message}")


def warn(message: str) -> None:
    print(f"{yellow('!')} {message}", file=sys.stderr)


def error(message: str) -> None:
    print(f"{red('✗')} {message}", file=sys.stderr)


def mask(secret: str) -> str:
    """Enough to recognise a password you already know, useless to anyone else."""
    if not secret:
        return dim("(empty)")
    if len(secret) <= 2:
        return "•" * len(secret)
    return f"{secret[0]}{'•' * (len(secret) - 2)}{secret[-1]} {dim(f'({len(secret)} chars)')}"


def table(rows: list[tuple[str, str]], indent: str = "  ") -> None:
    if not rows:
        return
    width = max(len(left) for left, _ in rows)
    for left, right in rows:
        print(f"{indent}{dim(left.ljust(width))}  {right}")
