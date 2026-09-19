# pdf-unlock

Bank and credit card statements arrive encrypted. Every tool downstream — your
notes app, a spreadsheet, an AI assistant, a script you wrote once and forgot —
hits the password prompt and stops.

`pdf-unlock` takes a locked PDF and writes a plain one. The original is never
modified, passwords live in your OS keyring rather than a config file, and once
you have told it how your banks build their passwords, you stop typing them.

```console
$ unlock ~/Downloads/HDFC_Statement_Aug.pdf
✓ HDFC_Statement_Aug.pdf → /Users/you/Documents/unlocked/HDFC_Statement_Aug.pdf
· 4 pages, AES-128; password from family hdfc-cc
```

It removes passwords you know. It is not a cracker.

---

## Install

```bash
uv tool install /path/to/pdf-unlock
pdf-unlock init
pdf-unlock shell-init >> ~/.zshrc   # gives you `unlock` and `unlocked`
```

## The idea: families

A bank rarely invents a password. It composes one from things it already knows
about you — four letters of your name, the day and month you were born, the last
four digits of the card. So rather than storing a dozen near-identical
passwords, store the fragments once and describe the recipe:

```bash
pdf-unlock identity set name          # prompts, hidden; goes to the Keychain
pdf-unlock identity set dob           # 1990-05-14

pdf-unlock family add --preset hdfc-cc
pdf-unlock family test hdfc-cc ~/Downloads/HDFC_Statement_Aug.pdf
```

`hdfc-cc` carries the template `{name|alpha|lower|first:4}{dob|date:%d%m}` and
matches any file whose name contains `hdfc`. New statement lands, the family
claims it, the password is derived, nothing is typed.

See what ships: `pdf-unlock family presets`. Presets are starting points —
issuers do change these, which is what `family test` is for.

### Writing your own recipe

Each placeholder is a field name followed by steps:

```
{surname|alpha|lower|first:4}{card_last4|digits|last:4}
```

| Step | Does |
|---|---|
| `lower` / `upper` | case |
| `alpha` / `digits` / `alnum` | keep only those characters |
| `nospace` / `strip` | whitespace |
| `first:N` / `last:N` | slice |
| `date:%d%m` | parse the field as a date and format it |

Two shorthands cover most uses: `{name:4}` is `{name|first:4}`, and `{dob:%d%m}`
is `{dob|date:%d%m}`.

```bash
pdf-unlock family add amex \
  --template '{surname|alpha|lower|first:4}{card_last4|last:4}' \
  --filename '*amex*' --note 'surname + card last 4'
```

### When you cannot be bothered

Families are the explainable path, not the only one. If nothing claims a file,
every password you have is tried anyway — for a personal keyring that costs
milliseconds, and a statement from a bank you never configured usually just
opens. One-offs still work the old way:

```bash
pdf-unlock statement.pdf -p 'the-password'
pdf-unlock password set hdfc-old         # store it for next time
```

## Everyday use

```bash
unlock statement.pdf                  # → output dir, then opens it
unlock ~/Downloads/*.pdf              # several at once
pdf-unlock inspect statement.pdf      # encryption, pages, which families match
pdf-unlock unlock x.pdf --dry-run     # what would be tried, in order
unlocked                              # cd to the output directory
unlocked 5                            # list the 5 most recent
```

## Configuration

`~/.config/pdf-unlock/config.toml`, or `$PDF_UNLOCK_CONFIG`.

```bash
pdf-unlock config show
pdf-unlock config set output_dir ~/Documents/unlocked
pdf-unlock config set open_after false
pdf-unlock config set copy_path true      # output path onto the clipboard
pdf-unlock config set suffix .unlocked    # a.pdf → a.unlocked.pdf
```

`PDF_UNLOCK_OUT` overrides the output directory for a single run.

Nothing in that file is secret. It holds field *names*, label *names* and family
rules; the values those names point at are in the keyring. So the file is safe
to read over your shoulder, diff, or sync.

## Where things live

| | |
|---|---|
| `engine/` | inspect, unlock, families, templates, config, keyring. No CLI dependencies. |
| `cli/` | argparse front end and the zsh snippet. |
| `web/` `api/` `mcp/` `docker/` | intentionally empty — see below. |

The engine/CLI split exists so the other surfaces can import the engine directly
when they are worth building. They are empty on purpose: for a tool that runs on
your own laptop, an API and a container are the same twenty lines wrapped in more
ceremony. The folders mark intent, not a backlog.

## What it does to your files

- The encrypted original is read, never written.
- Output is written to a temporary file, `chmod 600`, then moved into place — so
  a half-written PDF never appears under a real name.
- Passwords are never written to disk, never logged, and never printed (except
  `family test --show`, when you ask).
- Output files are decrypted financial documents. The output directory deserves
  the occasional clean-out.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
uv run pytest
uv run ruff check .
```

Tests generate their own encrypted PDFs across RC4-40, RC4-128, AES-128 and
AES-256, so nothing real is ever committed.

## Licence

MIT.
