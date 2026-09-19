"""pdf-unlock command line.

Built on argparse rather than a CLI framework so that `unlock statement.pdf`
starts in well under a tenth of a second. pikepdf and keyring are imported
lazily for the same reason -- `pdf-unlock --help` should not load a PDF library.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pdf_unlock_engine import (
    PRESETS,
    Config,
    Family,
    MatchRules,
    PdfUnlockError,
    __version__,
    build_plan,
    config_path,
    find_password,
    inspect_pdf,
    load_config,
    output_path_for,
    preset,
    render,
    save_config,
    unlock_pdf,
)
from pdf_unlock_engine.errors import NotEncryptedError, WrongPasswordError
from pdf_unlock_engine.secrets import IDENTITY, PASSWORD, delete_secret, get_secret, set_secret
from pdf_unlock_engine.templates import describe_steps

from . import ui

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NO_PASSWORD = 3

ENV_PASSWORD = "PDF_UNLOCK_PASSWORD"

COMMANDS = ("unlock", "inspect", "init", "identity", "password", "family", "config", "shell-init")


# --------------------------------------------------------------------------- #
# unlock
# --------------------------------------------------------------------------- #


def _reveal(files: list[Path], cfg: Config, args) -> None:
    if args.no_open or not (args.open or cfg.open_after) or not files:
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if not shutil.which(opener):
        return
    subprocess.run([opener, *[str(f) for f in files]], check=False)


def _copy_to_clipboard(paths: list[Path], cfg: Config, args) -> bool:
    if not (args.copy or cfg.copy_path) or not paths:
        return False
    if sys.platform != "darwin" or not shutil.which("pbcopy"):
        return False
    text = "\n".join(str(p) for p in paths)
    subprocess.run(["pbcopy"], input=text.encode(), check=False)
    return True


def _explicit_password(args) -> tuple[str, str] | None:
    """A password the user handed us directly, and where it came from."""
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n"), "stdin"
    if args.password is not None:
        return args.password, "--password"
    if env := os.environ.get(ENV_PASSWORD):
        return env, f"${ENV_PASSWORD}"
    return None


def _prompt_password(path: Path) -> str | None:
    if not sys.stdin.isatty():
        return None
    try:
        return getpass.getpass(f"Password for {path.name}: ") or None
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def _unlock_one(path: Path, cfg: Config, args, results: list[dict]) -> int:
    info = inspect_pdf(path)

    if not info.encrypted:
        ui.info(f"{ui.bold(path.name)} is not encrypted — nothing to do.")
        results.append({"source": str(path), "status": "not_encrypted"})
        return EXIT_OK

    given = _explicit_password(args)
    if given is not None:
        password, source = given
    else:
        plan = build_plan(info, cfg, only_family=args.family, try_all=not args.no_fallback)
        for warning in plan.warnings:
            ui.warn(warning)

        if args.dry_run:
            names = ", ".join(f.name for f in plan.matched) or "none"
            ui.info(f"{ui.bold(path.name)}: matched families: {names}")
            for cand in plan.candidates:
                ui.info(f"  would try {ui.cyan(cand.source)}")
            results.append(
                {
                    "source": str(path),
                    "status": "dry_run",
                    "matched": [f.name for f in plan.matched],
                    "candidates": [c.source for c in plan.candidates],
                }
            )
            return EXIT_OK

        hit = find_password(path, (c.as_pair() for c in plan.candidates))
        if hit is None:
            typed = None if args.no_prompt else _prompt_password(path)
            if typed is None:
                ui.error(
                    f"No password worked for {ui.bold(path.name)} "
                    f"({len(plan.candidates)} tried)."
                )
                ui.info("Try `pdf-unlock unlock --dry-run` to see what was attempted,")
                ui.info("or `pdf-unlock family add --preset <issuer>` to teach it this bank.")
                results.append({"source": str(path), "status": "no_password"})
                return EXIT_NO_PASSWORD
            password, source = typed, "typed"
        else:
            password, source = hit

    if args.dry_run:
        ui.info(f"{ui.bold(path.name)}: would unlock using {ui.cyan(source)}")
        results.append({"source": str(path), "status": "dry_run", "password_source": source})
        return EXIT_OK

    out_dir = Path(args.out).expanduser() if args.out else cfg.resolved_output_dir()
    dest = output_path_for(
        path, out_dir, suffix=args.suffix if args.suffix is not None else cfg.suffix,
        overwrite=args.overwrite or cfg.overwrite,
    )
    result = unlock_pdf(
        path,
        dest,
        password=password,
        password_source=source,
        overwrite=args.overwrite or cfg.overwrite,
        info=info,
    )

    detail = f"{result.page_count} pages"
    if result.encryption:
        detail += f", {result.encryption}"
    if result.restrictions_only:
        detail += ", owner restrictions only"
    ui.ok(f"{ui.bold(path.name)} → {ui.cyan(str(result.output))}")
    ui.info(f"{detail}; password from {source}")
    results.append(
        {
            "source": str(path),
            "output": str(result.output),
            "status": "unlocked",
            "password_source": source,
            "pages": result.page_count,
            "encryption": result.encryption,
        }
    )
    return EXIT_OK


def cmd_unlock(args, cfg: Config) -> int:
    results: list[dict] = []
    worst = EXIT_OK
    written: list[Path] = []

    for raw in args.files:
        path = Path(raw).expanduser()
        try:
            code = _unlock_one(path, cfg, args, results)
        except WrongPasswordError as exc:
            ui.error(str(exc))
            results.append({"source": str(path), "status": "wrong_password"})
            code = EXIT_NO_PASSWORD
        except PdfUnlockError as exc:
            ui.error(str(exc))
            results.append({"source": str(path), "status": "error", "error": str(exc)})
            code = EXIT_ERROR
        worst = max(worst, code)
        if results and results[-1].get("status") == "unlocked":
            written.append(Path(results[-1]["output"]))

    if _copy_to_clipboard(written, cfg, args):
        ui.info("path copied to clipboard")
    _reveal(written, cfg, args)

    if args.json:
        print(json.dumps(results, indent=2))
    return worst


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #


def cmd_inspect(args, cfg: Config) -> int:
    payload = []
    for raw in args.files:
        path = Path(raw).expanduser()
        info = inspect_pdf(path)
        plan = build_plan(info, cfg, try_all=True)

        if info.needs_password:
            state = ui.yellow("locked (password required to open)")
        elif info.encrypted:
            state = ui.yellow("owner restrictions only (opens without a password)")
        else:
            state = ui.green("not encrypted")

        print(ui.bold(path.name))
        rows = [("state", state)]
        if info.encryption:
            rows.append(("encryption", info.encryption))
        if info.page_count is not None:
            rows.append(("pages", str(info.page_count)))
        for label, value in (
            ("producer", info.producer),
            ("author", info.author),
            ("title", info.title),
        ):
            if value:
                rows.append((label, value))
        rows.append(
            ("families", ", ".join(f.name for f in plan.matched) or ui.dim("no match"))
        )
        rows.append(("candidates", str(len(plan.candidates))))
        ui.table(rows)
        print()

        payload.append(
            {
                "path": str(path),
                "encrypted": info.encrypted,
                "needs_password": info.needs_password,
                "encryption": info.encryption,
                "pages": info.page_count,
                "matched_families": [f.name for f in plan.matched],
                "candidate_count": len(plan.candidates),
            }
        )

    if args.json:
        print(json.dumps(payload, indent=2))
    return EXIT_OK


# --------------------------------------------------------------------------- #
# identity / password
# --------------------------------------------------------------------------- #


def _register(cfg: Config, bucket: str, name: str) -> None:
    names = getattr(cfg, bucket)
    if name not in names:
        names.append(name)
        names.sort()
        save_config(cfg)


def cmd_identity(args, cfg: Config) -> int:
    if args.identity_action == "list":
        if not cfg.identity_fields:
            ui.info("no identity fields yet — try `pdf-unlock identity set name`")
            return EXIT_OK
        rows = []
        for name in cfg.identity_fields:
            value = get_secret(IDENTITY, name)
            rows.append((name, ui.mask(value) if value else ui.red("not set")))
        ui.table(rows)
        return EXIT_OK

    if args.identity_action == "rm":
        removed = delete_secret(IDENTITY, args.name)
        if args.name in cfg.identity_fields:
            cfg.identity_fields.remove(args.name)
            save_config(cfg)
        ui.ok(f"removed {args.name}" if removed else f"{args.name} was not set")
        return EXIT_OK

    value = args.value
    if value is None:
        value = getpass.getpass(f"Value for {args.name} (hidden): ")
    if not value:
        ui.error("nothing entered")
        return EXIT_USAGE
    set_secret(IDENTITY, args.name, value)
    _register(cfg, "identity_fields", args.name)
    ui.ok(f"stored {ui.bold(args.name)} in the keyring")
    return EXIT_OK


def cmd_password(args, cfg: Config) -> int:
    if args.password_action == "list":
        if not cfg.password_labels:
            ui.info("no stored passwords yet — try `pdf-unlock password set hdfc-2024`")
            return EXIT_OK
        rows = []
        for name in cfg.password_labels:
            value = get_secret(PASSWORD, name)
            rows.append((name, ui.mask(value) if value else ui.red("not set")))
        ui.table(rows)
        return EXIT_OK

    if args.password_action == "rm":
        removed = delete_secret(PASSWORD, args.label)
        if args.label in cfg.password_labels:
            cfg.password_labels.remove(args.label)
            save_config(cfg)
        ui.ok(f"removed {args.label}" if removed else f"{args.label} was not stored")
        return EXIT_OK

    value = args.value
    if value is None:
        value = getpass.getpass(f"Password for {args.label} (hidden): ")
        if value and getpass.getpass("Again: ") != value:
            ui.error("the two entries did not match")
            return EXIT_USAGE
    if not value:
        ui.error("nothing entered")
        return EXIT_USAGE
    set_secret(PASSWORD, args.label, value)
    _register(cfg, "password_labels", args.label)
    ui.ok(f"stored password {ui.bold(args.label)} in the keyring")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# family
# --------------------------------------------------------------------------- #


def cmd_family(args, cfg: Config) -> int:
    action = args.family_action

    if action == "presets":
        print(ui.bold("Shipped presets"))
        print(ui.dim("Starting points — confirm one with `pdf-unlock family test <name> <file>`."))
        ui.table([(key, spec["note"]) for key, spec in sorted(PRESETS.items())])
        return EXIT_OK

    if action == "list":
        if not cfg.families:
            ui.info("no families yet — try `pdf-unlock family add --preset hdfc-cc`")
            return EXIT_OK
        for fam in cfg.families:
            print(ui.bold(fam.name) + (f"  {ui.dim(fam.note)}" if fam.note else ""))
            rows = []
            if fam.template:
                rows.append(("template", fam.template))
                missing = [f for f in fam.needs_fields if not get_secret(IDENTITY, f)]
                rows.append(
                    (
                        "needs",
                        ", ".join(fam.needs_fields)
                        + (f"  {ui.red('missing: ' + ', '.join(missing))}" if missing else ""),
                    )
                )
            if fam.secret:
                rows.append(("password", fam.secret))
            if fam.match.filename:
                rows.append(("filename", ", ".join(fam.match.filename)))
            if fam.match.filename_regex:
                rows.append(("filename_regex", ", ".join(fam.match.filename_regex)))
            for key in ("producer", "author", "title"):
                if value := getattr(fam.match, key):
                    rows.append((key, value))
            ui.table(rows)
            print()
        return EXIT_OK

    if action == "rm":
        if cfg.family(args.name) is None:
            ui.error(f"no family named {args.name!r}")
            return EXIT_USAGE
        cfg.families = [f for f in cfg.families if f.name != args.name]
        save_config(cfg)
        ui.ok(f"removed family {args.name}")
        return EXIT_OK

    if action == "add":
        fam = _family_from_args(args, cfg)
        if fam is None:
            return EXIT_USAGE
        if cfg.family(fam.name) and not args.force:
            ui.error(f"family {fam.name!r} already exists. Pass --force to replace it.")
            return EXIT_USAGE
        cfg.families = [f for f in cfg.families if f.name != fam.name] + [fam]
        save_config(cfg)
        ui.ok(f"added family {ui.bold(fam.name)}")
        if fam.template:
            missing = [f for f in fam.needs_fields if not get_secret(IDENTITY, f)]
            if missing:
                ui.warn(f"still needs: {', '.join(missing)}")
                for name in missing:
                    ui.info(f"  pdf-unlock identity set {name}")
        return EXIT_OK

    # action == "test"
    fam = cfg.family(args.name)
    if fam is None:
        ui.error(f"no family named {args.name!r}")
        return EXIT_USAGE

    if fam.secret:
        value = get_secret(PASSWORD, fam.secret)
        if not value:
            ui.error(f"stored password {fam.secret!r} is not in the keyring")
            return EXIT_ERROR
    else:
        identity = {}
        for name in fam.needs_fields:
            got = get_secret(IDENTITY, name)
            if got:
                identity[name] = got
        value = render(fam.template or "", identity)

    print(f"{ui.bold(fam.name)} produces: {value if args.show else ui.mask(value)}")
    if not args.show:
        ui.info("pass --show to print it in full")

    if args.file:
        path = Path(args.file).expanduser()
        info = inspect_pdf(path)
        from pdf_unlock_engine import verify_password

        if not info.encrypted:
            ui.info(f"{path.name} is not encrypted, so there is nothing to test against")
        elif verify_password(path, value):
            ui.ok(f"it opens {path.name}")
        else:
            ui.error(f"it does not open {path.name}")
            return EXIT_NO_PASSWORD
    return EXIT_OK


def _family_from_args(args, cfg: Config) -> Family | None:
    if args.preset:
        base = preset(args.preset, name=args.name)
        return Family(
            name=base.name,
            match=MatchRules(
                filename=args.filename or list(base.match.filename),
                filename_regex=args.filename_regex or [],
                producer=args.producer,
                author=args.author,
                title=args.title,
            ),
            template=args.template or base.template,
            note=args.note or base.note,
        )

    if not args.name:
        ui.error("give the family a name, or use --preset")
        return None
    if bool(args.template) == bool(args.secret):
        ui.error("pass exactly one of --template or --secret")
        ui.info("templates build a password from identity fields, e.g.")
        ui.info("  --template '{name|alpha|lower|first:4}{dob|date:%d%m}'")
        return None
    if not (args.filename or args.filename_regex or args.producer or args.author or args.title):
        ui.warn(
            "no match rules, so this family will only be used as a fallback. "
            "Add --filename '*hdfc*' to have it recognised by name."
        )
    return Family(
        name=args.name,
        match=MatchRules(
            filename=args.filename or [],
            filename_regex=args.filename_regex or [],
            producer=args.producer,
            author=args.author,
            title=args.title,
        ),
        template=args.template,
        secret=args.secret,
        note=args.note,
    )


# --------------------------------------------------------------------------- #
# config / init / shell-init
# --------------------------------------------------------------------------- #

_SETTABLE = {
    "output_dir": lambda v: Path(v),
    "open_after": lambda v: v.lower() in ("1", "true", "yes", "on"),
    "copy_path": lambda v: v.lower() in ("1", "true", "yes", "on"),
    "overwrite": lambda v: v.lower() in ("1", "true", "yes", "on"),
    "suffix": str,
}


def cmd_config(args, cfg: Config) -> int:
    if args.config_action == "path":
        print(config_path())
        return EXIT_OK

    if args.config_action == "show":
        from pdf_unlock_engine.config import dumps

        where = cfg.path or config_path()
        ui.info(f"{where}{'' if cfg.path else ui.dim('  (not created yet — showing defaults)')}")
        print(dumps(cfg))
        return EXIT_OK

    if args.config_action == "edit":
        path = save_config(cfg) if not cfg.path else cfg.path
        editor = os.environ.get("EDITOR", "vi")
        return subprocess.run([editor, str(path)], check=False).returncode

    key, value = args.key, args.value
    if key not in _SETTABLE:
        ui.error(f"unknown setting {key!r}. Settable: {', '.join(sorted(_SETTABLE))}")
        return EXIT_USAGE
    setattr(cfg, key, _SETTABLE[key](value))
    path = save_config(cfg)
    ui.ok(f"{key} = {getattr(cfg, key)}  {ui.dim(str(path))}")
    return EXIT_OK


def cmd_init(args, cfg: Config) -> int:
    interactive = sys.stdin.isatty() and not args.yes

    print(ui.bold("pdf-unlock setup"))
    print(ui.dim("Passwords are stored in your OS keyring, never in a file.\n"))

    if interactive:
        suggested = str(cfg.output_dir)
        answer = input(f"Where should unlocked PDFs go? [{suggested}] ").strip()
        if answer:
            cfg.output_dir = Path(answer)
    path = save_config(cfg)
    out = cfg.resolved_output_dir()
    out.mkdir(parents=True, exist_ok=True)
    ui.ok(f"config at {ui.cyan(str(path))}")
    ui.ok(f"output directory {ui.cyan(str(out))}")

    if interactive:
        for name, question in (
            ("name", "Name as the bank prints it (blank to skip)"),
            ("dob", "Date of birth, YYYY-MM-DD (blank to skip)"),
        ):
            if get_secret(IDENTITY, name):
                continue
            answer = input(f"{question}: ").strip()
            if answer:
                set_secret(IDENTITY, name, answer)
                _register(cfg, "identity_fields", name)
                ui.ok(f"stored {name}")

    print()
    ui.info("Next steps:")
    ui.info("  pdf-unlock family presets            # see the issuers we know")
    ui.info("  pdf-unlock family add --preset hdfc-cc")
    ui.info("  pdf-unlock shell-init >> ~/.zshrc    # add the `unlock` alias")
    return EXIT_OK


SHELL_SNIPPET = """
# --- pdf-unlock -------------------------------------------------------------
# `unlock statement.pdf` writes a password-free copy to your output directory
# and opens it. The encrypted original is never modified.
unlock() {
  command pdf-unlock unlock "$@"
}

# `unlocked` jumps to (or lists) the output directory.
unlocked() {
  local dir
  dir="$(command pdf-unlock config show 2>/dev/null | awk -F'\\"' '/^output_dir/ {print $2}')"
  dir="${dir/#\\~/$HOME}"
  if [ -n "$1" ]; then ls -lt "$dir" | head -n "$1"; else cd "$dir" || return; fi
}
# ----------------------------------------------------------------------------
"""


def cmd_shell_init(args, cfg: Config) -> int:
    print(SHELL_SNIPPET.strip())
    return EXIT_OK


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-unlock",
        description="Turn password-locked PDFs into plain ones.",
        epilog="Run `pdf-unlock init` once, then just `pdf-unlock statement.pdf`.",
    )
    parser.add_argument("--version", action="version", version=f"pdf-unlock {__version__}")
    parser.add_argument("--config", help="use this config file instead of the default")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("unlock", help="remove the password from one or more PDFs")
    p.add_argument("files", nargs="+")
    p.add_argument("-p", "--password", help="use this password (also reads $PDF_UNLOCK_PASSWORD)")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    p.add_argument("-o", "--out", help="output directory for this run")
    p.add_argument("--suffix", help="append to the stem, e.g. '.unlocked'")
    p.add_argument("-f", "--family", help="force a family instead of matching one")
    p.add_argument("--no-fallback", action="store_true", help="only try families that match")
    p.add_argument("--no-prompt", action="store_true", help="never ask interactively")
    p.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    p.add_argument("--open", action="store_true", help="open the result when done")
    p.add_argument("--no-open", action="store_true", help="do not open the result")
    p.add_argument("--copy", action="store_true", help="copy the output path to the clipboard")
    p.add_argument("--dry-run", action="store_true", help="show what would be tried, write nothing")
    p.add_argument("--json", action="store_true", help="also print machine-readable results")
    p.set_defaults(func=cmd_unlock)

    p = sub.add_parser("inspect", help="report a PDF's encryption and which families claim it")
    p.add_argument("files", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("init", help="create the config and store your first identity fields")
    p.add_argument("-y", "--yes", action="store_true", help="accept defaults, ask nothing")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("identity", help="identity fragments that templates are built from")
    isub = p.add_subparsers(dest="identity_action", required=True)
    q = isub.add_parser("set", help="store or replace a fragment")
    q.add_argument("name")
    q.add_argument("value", nargs="?", help="omit to be prompted without echo")
    isub.add_parser("list", help="show stored fragments, masked")
    q = isub.add_parser("rm", help="delete a fragment")
    q.add_argument("name")
    p.set_defaults(func=cmd_identity)

    p = sub.add_parser("password", help="literal passwords kept in the keyring")
    psub = p.add_subparsers(dest="password_action", required=True)
    q = psub.add_parser("set", help="store or replace a password")
    q.add_argument("label")
    q.add_argument("value", nargs="?", help="omit to be prompted without echo")
    psub.add_parser("list", help="show stored passwords, masked")
    q = psub.add_parser("rm", help="delete a stored password")
    q.add_argument("label")
    p.set_defaults(func=cmd_password)

    p = sub.add_parser(
        "family",
        help="groups of PDFs that share a password recipe",
        epilog="Template steps:\n" + describe_steps(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fsub = p.add_subparsers(dest="family_action", required=True)
    q = fsub.add_parser("add", help="create a family, from a preset or from scratch")
    q.add_argument("name", nargs="?")
    q.add_argument("--preset", choices=sorted(PRESETS), help="start from a shipped issuer preset")
    q.add_argument("--template", help="password recipe, e.g. '{name:4}{dob:%%d%%m}'")
    q.add_argument("--secret", help="label of a stored literal password to use instead")
    q.add_argument("--filename", action="append", help="glob against the filename (repeatable)")
    q.add_argument("--filename-regex", action="append", dest="filename_regex")
    q.add_argument("--producer", help="regex against the PDF's /Producer")
    q.add_argument("--author", help="regex against the PDF's /Author")
    q.add_argument("--title", help="regex against the PDF's /Title")
    q.add_argument("--note", help="a reminder of what the recipe means")
    q.add_argument("--force", action="store_true", help="replace an existing family")
    fsub.add_parser("list", help="show configured families")
    fsub.add_parser("presets", help="show the shipped issuer presets")
    q = fsub.add_parser("rm", help="delete a family")
    q.add_argument("name")
    q = fsub.add_parser("test", help="render a family's password, optionally against a file")
    q.add_argument("name")
    q.add_argument("file", nargs="?", help="check the password actually opens this PDF")
    q.add_argument("--show", action="store_true", help="print the password in full")
    p.set_defaults(func=cmd_family)

    p = sub.add_parser("config", help="inspect or change settings")
    csub = p.add_subparsers(dest="config_action", required=True)
    csub.add_parser("path", help="print the config file location")
    csub.add_parser("show", help="print the effective config")
    csub.add_parser("edit", help="open the config in $EDITOR")
    q = csub.add_parser("set", help="change one setting")
    q.add_argument("key", choices=sorted(_SETTABLE))
    q.add_argument("value")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("shell-init", help="print the zsh functions to add to ~/.zshrc")
    p.set_defaults(func=cmd_shell_init)

    return parser


def _with_default_command(argv: list[str]) -> list[str]:
    """`pdf-unlock statement.pdf` should mean `pdf-unlock unlock statement.pdf`.

    Global options have to stay in front of the subcommand, so step over those
    first and only then decide whether a command name is present.
    """
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help", "--version"):
            return argv
        if arg == "--config":
            i += 2
            continue
        if arg.startswith("--config="):
            i += 1
            continue
        break

    if i < len(argv) and argv[i] in COMMANDS:
        return argv
    return [*argv[:i], "unlock", *argv[i:]]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv:
        parser.print_help()
        return EXIT_USAGE

    args = parser.parse_args(_with_default_command(argv))
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE

    try:
        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        return args.func(args, cfg)
    except NotEncryptedError as exc:
        ui.info(str(exc))
        return EXIT_OK
    except PdfUnlockError as exc:
        ui.error(str(exc))
        return EXIT_ERROR
    except KeyboardInterrupt:
        print()
        return 130
    except BrokenPipeError:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
