# AGENTS.md — hummbl-clp

## Project

`hummbl-clp` is the Cognitive Ledger Protocol extraction lane: stdlib-only core with a staged decoupling plan from founder-mode services.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

## Conventions

- Python 3.11+ required
- Zero third-party runtime dependencies in core modules (deps only where justified)
- Conventional Commits format
- No secrets in code or docs

## Local validation

```powershell
C:\Users\Owner\bin\python.cmd tools\validate_repo.py
```

If tests exist and are available in environment:

```powershell
pytest -q
```

## Branch policy

- Branch naming: `type/agent/short-desc`
- PRs only; keep changes scoped to the task
- No `--no-verify` and no force-push to `main`
