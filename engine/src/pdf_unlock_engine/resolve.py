"""Deciding which passwords to try, and in what order.

Two mechanisms, in increasing order of laziness:

1. A family claims the file by name, and its template or stored password is tried
   first. This is the fast, explainable path.
2. Failing that, everything else you have is tried anyway. For a personal keyring
   with a handful of passwords this costs milliseconds, and it means a statement
   from a bank you never configured still tends to just open.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .families import Family, rank_families
from .inspect import PdfInfo
from .secrets import IDENTITY, PASSWORD, get_secret, load_identity
from .templates import TemplateError, render

__all__ = ["Candidate", "Plan", "build_plan"]


@dataclass(frozen=True)
class Candidate:
    password: str
    source: str
    """Provenance, e.g. "family hdfc-cc". Safe to print; the password is not."""

    def as_pair(self) -> tuple[str, str]:
        return self.password, self.source


@dataclass
class Plan:
    candidates: list[Candidate]
    matched: list[Family]
    """Families that claimed this file, most specific first."""
    warnings: list[str]
    """Things that stopped a candidate being built, e.g. a missing identity field."""


def _password_for(fam: Family, identity: dict[str, str]) -> tuple[str | None, str | None]:
    """Returns ``(password, warning)`` -- exactly one of them is set."""
    if fam.secret:
        value = get_secret(PASSWORD, fam.secret)
        if not value:
            return None, (
                f"family {fam.name!r} points at stored password {fam.secret!r}, "
                f"which is not in the keyring (run `pdf-unlock password set {fam.secret}`)"
            )
        return value, None
    try:
        return render(fam.template or "", identity), None
    except TemplateError as exc:
        return None, f"family {fam.name!r}: {exc}"


def build_plan(
    info: PdfInfo,
    cfg: Config,
    *,
    only_family: str | None = None,
    try_all: bool = True,
) -> Plan:
    """Work out the ordered list of passwords worth trying for this file."""
    identity = load_identity(cfg.identity_fields) if cfg.identity_fields else {}
    # Identity fields used by families but never registered would otherwise be
    # invisible; pick them up so a half-finished setup still works.
    extra = {f for fam in cfg.families for f in fam.needs_fields} - set(identity)
    for name in sorted(extra):
        if value := get_secret(IDENTITY, name):
            identity[name] = value

    candidates: list[Candidate] = []
    warnings: list[str] = []
    seen: set[str] = set()

    def add(password: str | None, source: str) -> None:
        # "" is a legitimate candidate (owner-restrictions-only files open with it),
        # so only None means "nothing to add".
        if password is not None and password not in seen:
            seen.add(password)
            candidates.append(Candidate(password, source))

    if only_family:
        fam = cfg.family(only_family)
        if fam is None:
            known = ", ".join(f.name for f in cfg.families) or "none configured"
            warnings.append(f"no family named {only_family!r}. Known families: {known}")
            return Plan([], [], warnings)
        password, warning = _password_for(fam, identity)
        if warning:
            warnings.append(warning)
        add(password, f"family {fam.name}")
        return Plan(candidates, [fam], warnings)

    matched = [fam for fam, _ in rank_families(info, cfg.families)]
    ordered = matched + ([f for f in cfg.families if f not in matched] if try_all else [])

    for fam in ordered:
        password, warning = _password_for(fam, identity)
        if warning and fam in matched:
            warnings.append(warning)
        label = f"family {fam.name}" + ("" if fam in matched else " (fallback)")
        add(password, label)

    if try_all:
        for name in cfg.password_labels:
            add(get_secret(PASSWORD, name), f"stored password {name}")
        # An empty password is what an owner-password-only file wants.
        add("", "no password (owner restrictions only)")

    return Plan(candidates, matched, warnings)
