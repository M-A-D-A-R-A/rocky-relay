# Security Notes

This repo is intended to be shared, so secrets must stay out of git.

## API Keys

Do not commit real provider keys in:

- `config.example.json`
- `README.md`
- `BENCHMARK.md`
- files under `docs/`
- source files under `src/`

Use environment variables instead:

```bash
export SMALLEST_API_KEY="..."
```

Or copy `.env.example` to `.env` for local use. `.env` is ignored by git.

## Pre-Commit Secret Check

Before committing, run:

```bash
rg -n --hidden --glob '!/.git/**' --glob '!outputs/**' --glob '!logs/**' \
  --glob '!models/**' --glob '!.venv/**' 'sk_[A-Za-z0-9_]+' .
```

Expected result:

```text
no matches
```

## If A Key Was Ever Written Locally

If a real key was accidentally placed in a file, even briefly, rotate or revoke
it before sharing the repo. The current working tree can be clean while shell
history, editor backups, or local copies still contain the old value.
