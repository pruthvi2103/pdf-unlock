# pdf-unlock

A CLI that writes a password-free copy of an encrypted PDF, aimed at bank and
credit card statements, so downstream tools (scripts, spreadsheets, AI) stop
hitting the password prompt. It removes passwords the user knows. It is not a
cracker, and nothing here should grow into one.

## Layout

| Path | What |
|---|---|
| `engine/src/pdf_unlock_engine/` | All the logic. No CLI dependencies, so future web/api/mcp surfaces import this directly. |
| `cli/src/pdf_unlock_cli/` | argparse front end plus the zsh snippet. |
| `tests/` | pytest, runs against generated PDFs and an in-memory keyring. |
| `web/` `api/` `mcp/` `docker/` | Empty on purpose. Do not populate without being asked. |

One distribution, two packages (see `[tool.hatch.build.targets.wheel]`). Keep the
one-way dependency: engine never imports cli.

### Engine modules

- `inspect.py`: what a PDF reveals *before* it is unlocked. An encrypted PDF
  hides its metadata, so for locked files the filename is essentially the only
  signal; this is why family matching is filename-first.
- `unlock.py`: the actual decryption. Deliberately the smallest module, since
  pikepdf wraps qpdf and the job is "open it, save it without encryption".
- `templates.py`: the mini-language that derives a password from identity
  fragments, e.g. `{name|alpha|lower|first:4}{dob|date:%d%m}`.
- `families.py`: a group of PDFs sharing one recipe, plus match rules and the
  shipped issuer presets.
- `resolve.py`: turns a file plus config into an ordered list of candidate
  passwords. Matching families first, then everything else as a fallback.
- `config.py` / `secrets.py`: the split that matters, below.

## Decisions worth not undoing

- **Config holds names, keyring holds values.** `config.toml` records identity
  field *names*, password *labels* and family rules. The values live in the OS
  keyring. The config file is therefore safe to read, diff or sync. Never write a
  secret into it.
- **Passwords are never printed or logged.** `Candidate.source` carries
  provenance ("family hdfc-cc"), never the password. The one exception is
  `family test --show`, which the user asks for explicitly.
- **The source file is never modified.** Output is written to a temp file,
  chmod 600, then atomically moved into place.
- **`overwrite` defaults to true.** The output directory holds derived files
  only, so replacing one is not destructive.
- **An empty string is a valid password candidate.** It is exactly what an
  owner-password-only PDF needs. Guard with `is not None`, never truthiness.
  This has been a bug twice.
- **argparse, not click/typer, and lazy pikepdf/keyring imports.** Startup is
  ~30ms and should stay that way. `--help` must not load a PDF library.
- **The shell snippet defines `pdf-unlocked` only.** The binary is already
  called `pdf-unlock` and already treats a bare file as `unlock`, so a wrapper
  function of the same name would add nothing and would break
  `pdf-unlock inspect`. Do not reintroduce a bare `unlock()` alias.
- **Preset case is verified, not assumed.** Every entry in `PRESETS` carries a
  `verified` flag, and `family presets` prints it. Only `hdfc-cc` is checked
  against a real statement (it uppercases the name; shipping `|lower` in
  v0.1.0 was a bug). Do not flip a preset's case without a real file proving
  it, and do not let a preset match on a card number: a Visa number starts
  with 4 whoever issued it, so that steals other issuers' files.
- **`SHELL_SNIPPET` is a raw string.** A stray escape there emits broken zsh
  into someone's ~/.zshrc. `test_shell_init_emits_valid_zsh` runs `zsh -n`
  over it.
- **Try-all fallback beats clever matching.** With a handful of personal
  passwords, trying them all costs milliseconds and means an unconfigured bank
  usually just works. Families are the explainable path, not the only one.

## Writing style

No em-dashes, anywhere: prose, docstrings, CLI output, commit messages. Use a
comma, a colon, or a full stop. Pruthvi asked for this explicitly.

## Commands

```bash
uv venv && uv pip install -e '.[dev]'
uv run pytest -q
uv run ruff check .
uv tool install --editable . # global `pdf-unlock`
```

## Testing conventions

- `tests/conftest.py` swaps in an in-memory keyring and an isolated config for
  every test, so the real Keychain is never touched. Keep both autouse.
- The `make_pdf` fixture generates encrypted PDFs on the spot. Nothing real is
  ever committed, and `.gitignore` blocks `*.pdf`.
- Cover all four security-handler revisions banks use: R2 (RC4-40), R3
  (RC4-128), R4 (AES-128), R6 (AES-256). R<4 needs `aes=False, metadata=False`.
- Pass `--no-open` in CLI tests so nothing launches Preview.
