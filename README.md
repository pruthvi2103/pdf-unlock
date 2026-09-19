# pdf-unlock

Takes a password-locked PDF and writes a plain one, so bank and credit card statements stop being the thing that breaks your automation.

| | |
|---|---|
| What it is | A CLI. `pdf-unlock statement.pdf` writes a decrypted copy and opens it. |
| Requires | Python 3.11+, macOS or Linux |
| Secrets | OS keyring (Keychain on macOS). Never on disk. |
| Status | v0.1.0 · 82 tests · ~30ms startup |

Read section 1 to get it running, section 3 if you want to stop typing passwords entirely. Section 5 is what it does to your files, with code references, if you would rather check than trust. Everything below has been run against generated PDFs at all four encryption revisions banks use.

**It removes passwords you know. It is not a cracker,** and there is no scope for it to become one.

-----

## 1. Run it

```bash
uv tool install --editable /path/to/pdf-unlock   # global `pdf-unlock` on your PATH
pdf-unlock init                                  # config + output directory
pdf-unlock shell-init >> ~/.zshrc                # adds the `pdf-unlocked` helper
```

`init` creates `~/.config/pdf-unlock/config.toml` and your output directory. It asks two questions and skips both if you pass `-y`.

`shell-init` adds exactly one function, `pdf-unlocked`. It does not alias `pdf-unlock`, because the binary already carries that name and already treats a bare file argument as `unlock`. A wrapper of the same name would rewrite `pdf-unlock inspect x.pdf` into `pdf-unlock unlock inspect x.pdf` and break it.

## 2. Driving it

| Command | Does |
|---|---|
| `pdf-unlock statement.pdf` | Unlock → output dir → open it |
| `pdf-unlock ~/Downloads/*.pdf` | Several in one run. One bad file does not stop the rest. |
| `pdf-unlock statement.pdf -p 'pw'` | Use this password, skip resolution |
| `pdf-unlock statement.pdf --dry-run` | Print what would be tried, in order, write nothing |
| `pdf-unlock inspect statement.pdf` | Encryption, page count, which families claim it |
| `pdf-unlock statement.pdf --json` | Machine-readable result on stdout |
| `pdf-unlocked` | cd to the output directory |
| `pdf-unlocked 5` | List the 5 newest files in it |

Exit codes: `0` fine, `1` error, `2` bad usage, `3` no password worked.

-----

## 3. Families

**A bank rarely invents a password.** It builds one from things it already knows about you: four letters of your name, the day and month you were born, the last four digits of the card. Storing a dozen near-identical passwords is dead weight. Store the fragments once and describe the recipe instead.

```bash
pdf-unlock identity set name          # prompts hidden, goes to the Keychain
pdf-unlock identity set dob           # 1990-05-14

pdf-unlock family add --preset hdfc-cc
pdf-unlock family test hdfc-cc ~/Downloads/HDFC_Statement_Aug.pdf
```

`hdfc-cc` carries the template `{name|alpha|upper|first:4}{dob|date:%d%m}` and claims any file whose name contains `hdfc`. A statement lands, the family recognises it, the password is derived, nothing is typed.

```console
$ pdf-unlock ~/Downloads/HDFC_Statement_Aug.pdf
✓ HDFC_Statement_Aug.pdf → /Users/you/Documents/unlocked/HDFC_Statement_Aug.pdf
· 4 pages, AES-128; password from family hdfc-cc
```

**Run `family test` before trusting a preset.** Seven ship (`pdf-unlock family presets`) covering HDFC, ICICI, Axis, SBI, Kotak and Amex. Each is marked `checked` or `unchecked`: only `hdfc-cc` has been confirmed against a real statement, and the rest are the common convention and nothing stronger.

**Case is the thing that bites.** PDF passwords are case-sensitive and no template can cover both, so `PRUT1405` and `prut1405` are different passwords and a wrong guess looks exactly like a wrong password. `hdfc-cc` shipped `|lower` in v0.1.0 and was wrong: HDFC uppercases the name. If a preset fails for you, flip `upper` and `lower` before anything else.

**Presets match on the issuer's name in the filename, which many statements do not have.** A file called `4854XXXXXXXXXX00_16-09-2026.pdf` is named after the card. Add your own rule for those:

```bash
pdf-unlock family add hdfc-cc --preset hdfc-cc --filename '4854*' --force
```

**Matching is filename-first, and that is not laziness.** An encrypted PDF will not reveal `/Producer` or `/Author` until it is already open, by which point the password is no longer needed. Metadata rules exist (`families.py:67`) and earn their keep on owner-password-only files, but the filename is the only signal available on a locked one.

### Writing a recipe

Each placeholder is a field name followed by steps, applied left to right:

```
{surname|alpha|lower|first:4}{card_last4|digits|last:4}
   │       │      │      │
   │       │      │      └── "shetty" → "shet"
   │       │      └───────── "Shetty" → "shetty"
   │       └──────────────── strip anything that is not a letter
   └──────────────────────── identity field, from the keyring
```

Steps, defined at `templates.py:77`:

| Step | Does |
|---|---|
| `lower` / `upper` | Case |
| `alpha` / `digits` / `alnum` | Keep only those characters |
| `nospace` / `strip` | Whitespace |
| `first:N` / `last:N` | Slice |
| `date:%d%m` | Parse the field as a date, then strftime it |

Two shorthands cover most real recipes. `{name:4}` means `{name|first:4}`, and `{dob:%d%m}` means `{dob|date:%d%m}`.

```bash
pdf-unlock family add amex \
  --template '{surname|alpha|lower|first:4}{card_last4|last:4}' \
  --filename '*amex*' --note 'surname + card last 4'
```

Dates are stored ISO (`1990-05-14`) and parsed from six formats, so `14/05/1990` and `14051990` work too.

### Conventions

- A family has a template **or** a stored password label, never both and never neither. Enforced at construction, not at unlock time.
- Templates are validated when the family is created, so a typo like `{name|shout}` fails at `family add` rather than at 11pm when you need the statement.
- A missing identity field reports **all** the missing fields at once, not the first one.
- `family test` masks the password by default. `--show` prints it, and that is the deliberate exception to "passwords are never printed".

### When you cannot be bothered

Families are the explainable path, not the only one. If nothing claims a file, every password you have is tried anyway (`unlock.py:52`). For a personal keyring that is milliseconds, and a statement from a bank you never configured usually just opens.

```bash
pdf-unlock statement.pdf -p 'the-password'   # one-off
pdf-unlock password set hdfc-old             # store it for next time
```

Pass `--no-fallback` to restrict to matching families only.

-----

## 4. Configuration

`~/.config/pdf-unlock/config.toml`, or wherever `$PDF_UNLOCK_CONFIG` points.

| Setting | Default | Notes |
|---|---|---|
| `output_dir` | `~/Documents/unlocked` | `$PDF_UNLOCK_OUT` overrides it for one run |
| `open_after` | `true` | Hands the result to `open` |
| `copy_path` | `false` | Output path onto the clipboard |
| `overwrite` | `true` | Safe: the output dir holds derived files only |
| `suffix` | `""` | `.unlocked` turns `a.pdf` into `a.unlocked.pdf` |

```bash
pdf-unlock config show
pdf-unlock config set output_dir ~/Documents/unlocked
pdf-unlock config set open_after false
```

**The config/keyring split is load-bearing.** The file holds field *names*, label *names* and family rules (`config.py:138`). The values those names point at live in the keyring under service `pdf-unlock` (`secrets.py:13`). Nothing secret is ever serialised, which is what makes the file safe to read over your shoulder, diff, or sync between machines.

*Note: `overwrite` defaults to true because the output directory contains only derived files. The encrypted original is never a write target.*

-----

## 5. What it does to your files (verified)

Every claim below has a code path. None are speculative.

| Claim | Where |
|---|---|
| The encrypted original is read, never written | `unlock.py:69`, which refuses a destination equal to the source |
| Output is `chmod 600` before it is visible | `unlock.py:127` |
| Output is written to a temp file, then atomically moved | `unlock.py:128`. A half-written PDF never appears under a real name. |
| Passwords are never logged or printed | `resolve.py:28`. `Candidate.source` carries provenance ("family hdfc-cc"), never the value. |
| A failed unlock leaves nothing behind | Temp file is removed on every error path |

**Limitation.** Output files are decrypted financial documents sitting in a directory. `chmod 600` stops other accounts on the machine, not anything with your login. The output directory deserves an occasional clean-out, and `pdf-unlock` will not do that for you.

**Limitation.** Passwords passed with `-p` are visible in your shell history and in `ps` output while the process runs. Use `--password-stdin` or a stored password if that matters to you.

## 6. What it deliberately does not do

| Not doing | Why |
|---|---|
| Guess or brute-force passwords | It tries passwords *you* have stored. Nothing more, and no dictionary or mask support is planned. |
| Ship `web/`, `api/`, `mcp/`, `docker/` | Folders exist with a README each explaining what would go there and what blocks it. For a tool on your own laptop, an API and a container are the same twenty lines wrapped in ceremony. |
| Use an LLM to identify issuers | Filename globs and metadata regexes are deterministic and free. Latency here would be indefensible. |
| Modify or delete your originals | There is no in-place mode, and adding one would mean destroying the encrypted copy. |
| Sync anything anywhere | No network calls at all, by design. |

The `engine/` and `cli/` split (883 lines of engine, no CLI imports) exists so those surfaces can import the engine directly when one of them is worth building. `mcp/` is the likeliest next one.

-----

## 7. Development

```bash
uv venv && uv pip install -e '.[dev]'
uv run pytest        # 82 tests, ~0.7s
uv run ruff check .
```

Tests generate their own encrypted PDFs at revisions R2 (RC4-40), R3 (RC4-128), R4 (AES-128) and R6 (AES-256), and swap in an in-memory keyring, so the real Keychain is never touched and no statement is ever committed. `.gitignore` blocks `*.pdf` as a second line of defence.

`CLAUDE.md` records the decisions worth not undoing, including two bugs that are easy to reintroduce.

## Licence

MIT. Questions: open an issue.
