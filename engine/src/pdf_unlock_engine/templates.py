"""The tiny language families use to derive a password from identity fragments.

Banks rarely invent a password; they compose one out of things they already know
about you. HDFC wants the first four letters of your name plus the day and month
you were born. Amex wants four letters of your surname plus the last four digits
of the card. So instead of storing a dozen near-identical passwords, you store
the fragments once and describe the recipe:

    {name|alpha|lower|first:4}{dob|date:%d%m}   ->  prut1405

Every placeholder is a pipeline: a field name followed by zero or more steps.
Two shorthands cover the common cases -- ``{name:4}`` means ``{name|first:4}``
and ``{dob:%d%m}`` means ``{dob|date:%d%m}``.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .errors import PdfUnlockError

__all__ = ["TemplateError", "render", "validate", "fields_used", "STEPS", "describe_steps"]


class TemplateError(PdfUnlockError):
    """The template is malformed, or an identity field it needs is missing."""


_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d%m%Y",
    "%Y/%m/%d",
)


def _parse_date(value: str, field: str) -> date:
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise TemplateError(
        f"field {field!r} is used as a date but {text!r} is not one; "
        "use YYYY-MM-DD (e.g. 1990-05-14)"
    )


def _step_first(value: str, arg: str, field: str) -> str:
    return value[: _count(arg, field, "first")]


def _step_last(value: str, arg: str, field: str) -> str:
    return value[-_count(arg, field, "last") :]


def _step_date(value: str, arg: str, field: str) -> str:
    if not arg:
        raise TemplateError(f"step 'date' on field {field!r} needs a format, e.g. date:%d%m")
    return _parse_date(value, field).strftime(arg)


def _count(arg: str, field: str, step: str) -> int:
    if not arg.isdigit() or int(arg) <= 0:
        raise TemplateError(
            f"step {step!r} on field {field!r} needs a positive number, got {arg!r}"
        )
    return int(arg)


STEPS: dict[str, str] = {
    "lower": "lowercase",
    "upper": "UPPERCASE",
    "alpha": "keep letters only",
    "digits": "keep digits only",
    "alnum": "keep letters and digits",
    "nospace": "remove whitespace",
    "strip": "trim surrounding whitespace",
    "first": "first N characters, e.g. first:4",
    "last": "last N characters, e.g. last:4",
    "date": "format as a date, e.g. date:%d%m",
}

_SIMPLE = {
    "lower": str.lower,
    "upper": str.upper,
    "alpha": lambda v: "".join(c for c in v if c.isalpha()),
    "digits": lambda v: "".join(c for c in v if c.isdigit()),
    "alnum": lambda v: "".join(c for c in v if c.isalnum()),
    "nospace": lambda v: "".join(v.split()),
    "strip": str.strip,
}

_WITH_ARG = {"first": _step_first, "last": _step_last, "date": _step_date}


def describe_steps() -> str:
    width = max(len(name) for name in STEPS)
    return "\n".join(f"  {name:<{width}}  {desc}" for name, desc in STEPS.items())


def _expand_shorthand(spec: str) -> str:
    """``4`` becomes ``first:4``; ``%d%m`` becomes ``date:%d%m``."""
    if "%" in spec:
        return f"date:{spec}"
    if spec.isdigit():
        return f"first:{spec}"
    if spec.startswith("-") and spec[1:].isdigit():
        return f"last:{spec[1:]}"
    return spec


def _split_placeholder(body: str) -> tuple[str, list[str]]:
    head, _, tail = body.partition("|")
    field, _, spec = head.partition(":")
    field = field.strip()
    if not field:
        raise TemplateError(f"placeholder {{{body}}} has no field name")

    steps: list[str] = []
    if spec.strip():
        steps.append(_expand_shorthand(spec.strip()))
    steps.extend(part.strip() for part in tail.split("|") if part.strip())
    return field, steps


def _check_step(step: str, field: str) -> tuple[str, str]:
    """Validate a step without running it. Returns ``(name, arg)``."""
    name, _, arg = step.partition(":")
    name, arg = name.strip(), arg.strip()

    if name in _SIMPLE:
        if arg:
            raise TemplateError(f"step {name!r} on field {field!r} takes no argument")
    elif name in ("first", "last"):
        _count(arg, field, name)
    elif name == "date":
        if not arg:
            raise TemplateError(f"step 'date' on field {field!r} needs a format, e.g. date:%d%m")
    else:
        raise TemplateError(
            f"unknown step {name!r} on field {field!r}. Available steps:\n{describe_steps()}"
        )
    return name, arg


def _apply(value: str, step: str, field: str) -> str:
    name, arg = _check_step(step, field)
    if name in _SIMPLE:
        return _SIMPLE[name](value)
    return _WITH_ARG[name](value, arg, field)


def validate(template: str) -> None:
    """Raise TemplateError if the template is malformed. Needs no identity values."""
    for match in _PLACEHOLDER.finditer(_mask_literals(template)):
        field, steps = _split_placeholder(match.group(1))
        for step in steps:
            _check_step(step, field)


def fields_used(template: str) -> list[str]:
    """Identity field names the template needs, in order of first appearance."""
    seen: list[str] = []
    for match in _PLACEHOLDER.finditer(_mask_literals(template)):
        field, _ = _split_placeholder(match.group(1))
        if field not in seen:
            seen.append(field)
    return seen


def _mask_literals(template: str) -> str:
    """Blank out ``{{``/``}}`` so they are not read as placeholders."""
    return template.replace("{{", "\0\0").replace("}}", "\0\0")


def render(template: str, identity: dict[str, str]) -> str:
    """Build a password from ``template`` and the caller's identity fragments.

    Raises TemplateError naming the field when something is missing, so the CLI
    can tell you exactly which fragment to set.
    """
    masked = _mask_literals(template)
    validate(template)

    missing = [f for f in fields_used(template) if not identity.get(f)]
    if missing:
        names = ", ".join(repr(f) for f in missing)
        how = "; ".join(f"pdf-unlock identity set {f}" for f in missing)
        raise TemplateError(f"identity field(s) not set: {names}. Run: {how}")

    out: list[str] = []
    cursor = 0

    for match in _PLACEHOLDER.finditer(masked):
        out.append(template[cursor : match.start()])
        field, steps = _split_placeholder(match.group(1))
        value = str(identity[field])
        for step in steps:
            value = _apply(value, step, field)
        out.append(value)
        cursor = match.end()

    out.append(template[cursor:])
    return "".join(out).replace("{{", "{").replace("}}", "}")
