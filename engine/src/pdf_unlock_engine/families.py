"""Families: groups of PDFs that share one password recipe.

A family is "every HDFC credit card statement" or "my Amex bills". It carries
match rules that recognise a file, plus either a password template (built from
identity fragments) or the label of a literal password kept in the keyring.

Matching leans on the filename because an encrypted PDF will not reveal its
metadata until after it is open -- by which point we no longer need to guess.
Metadata rules still earn their keep for owner-password-only files and when a
family is tested against an already-unlocked PDF.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

from .errors import ConfigError
from .inspect import PdfInfo
from .templates import fields_used, validate

__all__ = ["Family", "MatchRules", "match_family", "rank_families", "PRESETS", "preset"]


@dataclass(frozen=True)
class MatchRules:
    """How a family recognises one of its files."""

    filename: list[str] = field(default_factory=list)
    """Case-insensitive glob patterns against the basename, e.g. ``*hdfc*.pdf``."""
    filename_regex: list[str] = field(default_factory=list)
    producer: str | None = None
    author: str | None = None
    title: str | None = None

    def is_empty(self) -> bool:
        return not (
            self.filename or self.filename_regex or self.producer or self.author or self.title
        )


@dataclass(frozen=True)
class Family:
    name: str
    match: MatchRules = field(default_factory=MatchRules)
    template: str | None = None
    """Password recipe, e.g. ``{name|alpha|lower|first:4}{dob|date:%d%m}``."""
    secret: str | None = None
    """Label of a literal password held in the OS keyring."""
    note: str | None = None

    def __post_init__(self) -> None:
        if bool(self.template) == bool(self.secret):
            raise ConfigError(
                f"family {self.name!r} must have exactly one of a template or a stored "
                "password label, not both and not neither"
            )
        if self.template:
            validate(self.template)  # surfaces malformed templates at load time

    @property
    def needs_fields(self) -> list[str]:
        return fields_used(self.template) if self.template else []


def _matches_name(info: PdfInfo, rules: MatchRules) -> int:
    hits = 0
    basename = info.path.name
    lowered = basename.lower()
    for pattern in rules.filename:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            hits += 1
            break
    for pattern in rules.filename_regex:
        try:
            if re.search(pattern, basename, re.IGNORECASE):
                hits += 1
                break
        except re.error as exc:
            raise ConfigError(f"bad filename_regex {pattern!r}: {exc}") from exc
    return hits


def _matches_metadata(info: PdfInfo, rules: MatchRules) -> int:
    hits = 0
    for pattern, value in (
        (rules.producer, info.producer),
        (rules.author, info.author),
        (rules.title, info.title),
    ):
        if pattern and value and re.search(pattern, value, re.IGNORECASE):
            hits += 1
    return hits


def score(info: PdfInfo, fam: Family) -> int:
    """How strongly ``fam`` claims this file. 0 means no claim."""
    if fam.match.is_empty():
        return 0
    return _matches_name(info, fam.match) + _matches_metadata(info, fam.match)


def rank_families(info: PdfInfo, families: list[Family]) -> list[tuple[Family, int]]:
    """Families that claim this file, most specific first."""
    scored = [(fam, score(info, fam)) for fam in families]
    return sorted(
        ((fam, s) for fam, s in scored if s > 0),
        key=lambda pair: pair[1],
        reverse=True,
    )


def match_family(info: PdfInfo, families: list[Family]) -> Family | None:
    ranked = rank_families(info, families)
    return ranked[0][0] if ranked else None


# Starting points for issuers with well-known conventions. A head start, not
# gospel: issuers change these, so run `pdf-unlock family test` before trusting one.
#
# Case matters, because PDF passwords are case-sensitive and there is no way to
# cover both with a single template. Only hdfc-cc has been checked against a real
# statement; the rest carry "verified": False and are the common convention, no
# more than that. If one of them fails for you, try flipping upper/lower first.
#
# Filename rules assume the issuer's name is in the filename. Many statements are
# named after the card instead ("4854XXXXXXXXXX00_16-09-2026.pdf"), which carries
# no issuer at all. Add your own rule for those:
#     pdf-unlock family add hdfc-cc --preset hdfc-cc --filename '4854*' --force
PRESETS: dict[str, dict] = {
    "hdfc-cc": {
        "template": "{name|alpha|upper|first:4}{dob|date:%d%m}",
        "filename": ["*hdfc*"],
        "note": "first 4 letters of name in CAPS + DDMM of birth",
        "verified": True,
    },
    "icici-cc": {
        "template": "{name|alpha|upper|first:4}{dob|date:%d%m}",
        "filename": ["*icici*"],
        "note": "first 4 letters of name in CAPS + DDMM of birth",
        "verified": False,
    },
    "axis-cc": {
        "template": "{name|alpha|upper|first:4}{dob|date:%d%m}",
        "filename": ["*axis*"],
        "note": "first 4 letters of name in CAPS + DDMM of birth",
        "verified": False,
    },
    "sbi-cc": {
        "template": "{dob|date:%d%m%Y}",
        "filename": ["*sbi*", "*sbicard*"],
        "note": "DDMMYYYY of birth",
        "verified": False,
    },
    "amex": {
        "template": "{surname|alpha|upper|first:4}{card_last4|digits|last:4}",
        "filename": ["*amex*", "*americanexpress*"],
        "note": "first 4 letters of surname in CAPS + last 4 digits of the card",
        "verified": False,
    },
    "kotak": {
        "template": "{name|alpha|upper|first:4}{dob|date:%d%m}",
        "filename": ["*kotak*"],
        "note": "first 4 letters of name in CAPS + DDMM of birth",
        "verified": False,
    },
    "hdfc-bank": {
        "template": "{customer_id|digits}",
        "filename": ["*hdfc*bank*", "*acct*hdfc*"],
        "note": "customer ID",
        "verified": False,
    },
}


def preset(key: str, name: str | None = None) -> Family:
    """Build a Family from a shipped preset."""
    if key not in PRESETS:
        known = ", ".join(sorted(PRESETS))
        raise ConfigError(f"unknown preset {key!r}. Known presets: {known}")
    spec = PRESETS[key]
    return Family(
        name=name or key,
        match=MatchRules(filename=list(spec["filename"])),
        template=spec["template"],
        note=spec["note"],
    )
