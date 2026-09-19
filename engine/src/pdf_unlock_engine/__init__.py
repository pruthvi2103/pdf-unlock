"""pdf-unlock engine: turn a password-locked PDF into a plain one.

The engine has no CLI dependencies, so the planned web, api and mcp surfaces can
import it directly.

    from pdf_unlock_engine import inspect_pdf, unlock_pdf

    info = inspect_pdf("statement.pdf")
    if info.needs_password:
        unlock_pdf("statement.pdf", "out.pdf", password="prut1405")
"""

from .config import Config, config_path, load_config, save_config
from .errors import (
    ConfigError,
    NoPasswordFoundError,
    NotAPdfError,
    NotEncryptedError,
    OutputExistsError,
    PdfUnlockError,
    SecretsError,
    WrongPasswordError,
)
from .families import PRESETS, Family, MatchRules, match_family, preset, rank_families
from .inspect import PdfInfo, inspect_pdf
from .resolve import Candidate, Plan, build_plan
from .templates import TemplateError, fields_used, render
from .unlock import UnlockResult, find_password, output_path_for, unlock_pdf, verify_password

__version__ = "0.1.0"

__all__ = [
    "Candidate",
    "Config",
    "ConfigError",
    "Family",
    "MatchRules",
    "NoPasswordFoundError",
    "NotAPdfError",
    "NotEncryptedError",
    "OutputExistsError",
    "PRESETS",
    "PdfInfo",
    "PdfUnlockError",
    "Plan",
    "SecretsError",
    "TemplateError",
    "UnlockResult",
    "WrongPasswordError",
    "__version__",
    "build_plan",
    "config_path",
    "fields_used",
    "find_password",
    "inspect_pdf",
    "load_config",
    "match_family",
    "output_path_for",
    "preset",
    "rank_families",
    "render",
    "save_config",
    "unlock_pdf",
    "verify_password",
]
