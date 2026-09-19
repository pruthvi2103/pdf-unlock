# pdf-unlock

Bank and credit card statements arrive encrypted. Every tool downstream stops at
the password prompt: your notes app, a spreadsheet, an AI assistant, a script you
wrote once and forgot about.

`pdf-unlock` takes a locked PDF and writes a plain one. The original is never
modified, passwords live in your OS keyring instead of a config file, and once
you tell it how your banks build their passwords, you stop typing them.

```console
$ pdf-unlock ~/Downloads/HDFC_Statement_Aug.pdf
✓ HDFC_Statement_Aug.pdf → /Users/you/Documents/unlocked/HDFC_Statement_Aug.pdf
· 4 pages, AES-128; password from family hdfc-cc
```

It removes passwords you know. It is not a cracker.

## Install

```bash
uv tool install --editable /path/to/pdf-unlock
pdf-unlock init
pdf-unlock shell-init >> ~/.zshrc
```

`shell-init` adds one helper, `pdf-unlocked`, which jumps to your output
directory. `pdf-unlocked 5` lists the 5 newest files instead.

## Families

A bank rarely invents a password. It builds one out of things it already knows
about you: four letters of your name, the day and month you were born, the last
four digits of the card. So instead of storing a dozen near-identical passwords,
store the fragments once and describe the recipe.

```bash
pdf-unlock identity set name          # prompts, hidden; goes to the Keychain
pdf-unlock identity set dob           # 1990-05-14

pdf-unlock family add --preset hdfc-cc
pdf-unlock family test hdfc-cc ~/Downloads/HDFC_Statement_Aug.pdf
```

`hdfc-cc` carries the template `{name|alpha|lower|first:4}{dob|date:%d%m}` and
claims any file whose name contains `hdfc`. A new statement lands, the family
recognises it, the password is derived, nothing is typed.

Run `pdf-unlock family presets` to see what ships. Presets are starting points,
not guarantees. Issuers do change these, which is what `family test` is for.

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

Two shorthands cover most uses. `{name:4}` means `{name|first:4}`, and
`{dob:%d%m}` means `{dob|date:%d%m}`.

```bash
pdf-unlock family add amex \
  --template '{surname|alpha|lower|first:4}{card_last4|last:4}' \
  --filename '*amex*' --note 'surname + card last 4'
```

### When you cannot be bothered

Families are the explainable path, not the only one. If nothing claims a file,
every password you have is tried anyway. For a personal keyring that costs
milliseconds, and a statement from a bank you never configured usually just
opens.

One-offs still work the old way:

```bash
pdf-unlock statement.pdf -p 'the-password'
pdf-unlock password set hdfc-old         # store it for next time
```

## Everyday use

```bash
pdf-unlock statement.pdf              # to the output dir, then opens it
pdf-unlock ~/Downloads/*.pdf          # several at once
pdf-unlock inspect statement.pdf      # encryption, pages, which families match
pdf-unlock statement.pdf --dry-run    # what would be tried, in order
pdf-unlocked                          # cd to the output directory
pdf-unlocked 5                        # list the 5 most recent
```

## Configuration

Lives at `~/.config/pdf-unlock/config.toml`, or wherever `$PDF_UNLOCK_CONFIG`
points.

```bash
pdf-unlock config show
pdf-unlock config set output_dir ~/Documents/unlocked
pdf-unlock config set open_after false
pdf-unlock config set copy_path true      # output path onto the clipboard
pdf-unlock config set suffix .unlocked    # a.pdf becomes a.unlocked.pdf
```

`PDF_UNLOCK_OUT` overrides the output directory for a single run.

Nothing in that file is secret. It holds field names, label names and family
rules. The values those names point at are in the keyring, so the file is safe
to read over your shoulder, diff, or sync.

## Layout

| | |
|---|---|
| `engine/` | inspect, unlock, families, templates, config, keyring. No CLI dependencies. |
| `cli/` | argparse front end and the zsh snippet. |
| `web/` `api/` `mcp/` `docker/` | Intentionally empty. Each has a README saying what would go there. |

The engine/CLI split exists so the other surfaces can import the engine directly
when they are worth building. They are empty on purpose. For a tool that runs on
your own laptop, an API and a container are the same twenty lines wrapped in more
ceremony. The folders mark intent, not a backlog.

## What it does to your files

1. The encrypted original is read, never written.
2. Output goes to a temporary file, `chmod 600`, then moves into place. A
   half-written PDF never appears under a real name.
3. Passwords are never written to disk, never logged, never printed. The one
   exception is `family test --show`, when you ask for it.
4. Output files are decrypted financial documents. The output directory deserves
   an occasional clean-out.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
uv run pytest
uv run ruff check .
```

Tests generate their own encrypted PDFs across RC4-40, RC4-128, AES-128 and
AES-256, and swap in an in-memory keyring, so nothing real is ever committed or
touched.

## Licence

MIT.
