"""Reading and writing ~/.config/pdf-unlock/config.toml.

Everything in this file is non-secret by construction: field *names*, label
*names*, family rules and templates. The values those names point at live in the
keyring (see secrets.py), so this file stays safe to read over someone's shoulder.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .errors import ConfigError
from .families import Family, MatchRules

__all__ = ["Config", "config_path", "load_config", "save_config", "DEFAULT_OUTPUT_DIR"]

DEFAULT_OUTPUT_DIR = "~/Documents/unlocked"
ENV_CONFIG = "PDF_UNLOCK_CONFIG"
ENV_OUTPUT_DIR = "PDF_UNLOCK_OUT"


@dataclass
class Config:
    output_dir: Path = Path(DEFAULT_OUTPUT_DIR)
    open_after: bool = True
    """Hand the unlocked file to `open` once it is written."""
    copy_path: bool = False
    """Put the output path on the clipboard, for pasting into another tool."""
    overwrite: bool = True
    """Replace an existing unlocked copy. Safe by default: the encrypted
    original is never touched, so the output directory holds only derived files."""
    suffix: str = ""
    """Appended to the stem, e.g. ".unlocked" turns a.pdf into a.unlocked.pdf."""
    identity_fields: list[str] = field(default_factory=list)
    password_labels: list[str] = field(default_factory=list)
    families: list[Family] = field(default_factory=list)
    path: Path | None = None
    """Where this config was read from. None when nothing existed yet."""

    def family(self, name: str) -> Family | None:
        return next((f for f in self.families if f.name == name), None)

    def resolved_output_dir(self) -> Path:
        return Path(os.path.expanduser(str(self.output_dir))).resolve()

    def with_family(self, fam: Family) -> Config:
        others = [f for f in self.families if f.name != fam.name]
        return replace(self, families=[*others, fam])


def config_path() -> Path:
    if override := os.environ.get(ENV_CONFIG):
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "pdf-unlock" / "config.toml"


def _as_str_list(raw, where: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ConfigError(f"{where} must be a list of strings")
    return list(raw)


def _family_from_toml(raw: dict, index: int) -> Family:
    where = f"[[family]] #{index + 1}"
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{where} needs a name")
    return Family(
        name=name,
        match=MatchRules(
            filename=_as_str_list(raw.get("filename"), f"{where} filename"),
            filename_regex=_as_str_list(raw.get("filename_regex"), f"{where} filename_regex"),
            producer=raw.get("producer"),
            author=raw.get("author"),
            title=raw.get("title"),
        ),
        template=raw.get("template"),
        secret=raw.get("secret"),
        note=raw.get("note"),
    )


def load_config(path: Path | None = None) -> Config:
    """Read the config, or return defaults when the file does not exist yet."""
    path = path or config_path()
    if not path.is_file():
        cfg = Config()
        if env_out := os.environ.get(ENV_OUTPUT_DIR):
            cfg.output_dir = Path(env_out)
        return cfg

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc

    families = [_family_from_toml(item, i) for i, item in enumerate(raw.get("family", []))]
    names = [f.name for f in families]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ConfigError(f"duplicate family names in {path}: {', '.join(dupes)}")

    cfg = Config(
        output_dir=Path(raw.get("output_dir", DEFAULT_OUTPUT_DIR)),
        open_after=bool(raw.get("open_after", True)),
        copy_path=bool(raw.get("copy_path", False)),
        overwrite=bool(raw.get("overwrite", True)),
        suffix=str(raw.get("suffix", "")),
        identity_fields=_as_str_list(raw.get("identity_fields"), "identity_fields"),
        password_labels=_as_str_list(raw.get("password_labels"), "password_labels"),
        families=families,
        path=path,
    )
    # The environment wins over the file, so a one-off `PDF_UNLOCK_OUT=... unlock x.pdf` works.
    if env_out := os.environ.get(ENV_OUTPUT_DIR):
        cfg.output_dir = Path(env_out)
    return cfg


def _toml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def dumps(cfg: Config) -> str:
    lines = [
        "# pdf-unlock configuration.",
        "#",
        "# Nothing here is secret. Passwords and identity fragments are stored in the",
        "# OS keyring; this file only records their names and how families match files.",
        "",
        f"output_dir = {_toml_str(str(cfg.output_dir))}",
        f"open_after = {str(cfg.open_after).lower()}",
        f"copy_path = {str(cfg.copy_path).lower()}",
        f"overwrite = {str(cfg.overwrite).lower()}",
        f"suffix = {_toml_str(cfg.suffix)}",
        "",
        "# Names only -- the values live in the keyring.",
        f"identity_fields = {_toml_list(cfg.identity_fields)}",
        f"password_labels = {_toml_list(cfg.password_labels)}",
    ]
    for fam in cfg.families:
        lines += ["", "[[family]]", f"name = {_toml_str(fam.name)}"]
        if fam.template:
            lines.append(f"template = {_toml_str(fam.template)}")
        if fam.secret:
            lines.append(f"secret = {_toml_str(fam.secret)}")
        if fam.note:
            lines.append(f"note = {_toml_str(fam.note)}")
        if fam.match.filename:
            lines.append(f"filename = {_toml_list(fam.match.filename)}")
        if fam.match.filename_regex:
            lines.append(f"filename_regex = {_toml_list(fam.match.filename_regex)}")
        for key in ("producer", "author", "title"):
            if value := getattr(fam.match, key):
                lines.append(f"{key} = {_toml_str(value)}")
    return "\n".join(lines) + "\n"


def save_config(cfg: Config, path: Path | None = None) -> Path:
    path = path or cfg.path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dumps(cfg), encoding="utf-8")
    tmp.replace(path)
    cfg.path = path
    return path
