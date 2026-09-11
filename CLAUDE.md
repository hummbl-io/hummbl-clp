# CLAUDE.md

## Project

**hummbl-clp** -- Cognitive Ledger Protocol. Shared memory for multi-agent
coordination: append-only JSONL ledger, BM25 inverted index, SQLite FTS5
search, Zettelkasten-style links, HMAC-SHA256 signing, content scanning.
Part of the HUMMBL ecosystem.

## Architecture

Three layers:
1. **Shared State** (`state.json`) -- mutable snapshot, optimistic concurrency
2. **Shared Memory** (`ledger.jsonl`) -- append-only learning log
3. **Shared Intent** (`intent.md`) -- human-authored goals

Core modules (`src/hummbl_clp/core/`): stdlib-only, self-contained.
Extension modules (`src/hummbl_clp/extensions/`): coupled to founder-mode,
pending decoupling (see ROADMAP.md).

## Commands

```bash
# Install
pip install -e ".[test]"

# Validate repo baseline
C:\Users\Owner\bin\python.cmd tools\validate_repo.py

# Run tests
pytest -q

# CLI usage
hummbl-clp post --agent <name> --vendor <vendor> --model <model> --type <type> --scope <scope> --content "<text>"
hummbl-clp query --type lesson --limit 20
hummbl-clp search "oauth token" --limit 10
hummbl-clp graph clp-abc123def456 --depth 5
hummbl-clp reindex
hummbl-clp validate
hummbl-clp state
hummbl-clp boot --max-entries 20
```

## Conventions

- Python 3.11+ required
- Zero third-party runtime dependencies in core (stdlib-only)
- Commit format: Conventional Commits
- No AI agent attribution in commit metadata or trailers
- All claims must cite sources or be tagged UNVERIFIED
- No secrets in code or docs
- Branch naming: `type/agent/short-desc`
- PRs only; keep changes scoped to the task
- No `--no-verify` and no force-push to `main`

## Key files

- `src/hummbl_clp/core/models.py` -- LedgerEntry, SharedState data models
- `src/hummbl_clp/core/ledger_writer.py` -- append-only JSONL writer, content scanning, HMAC signing
- `src/hummbl_clp/core/query.py` -- query engine, supersedes resolution, boot summary
- `src/hummbl_clp/core/indexer.py` -- BM25 inverted term index
- `src/hummbl_clp/core/sqlite_indexer.py` -- SQLite FTS5 index, graph traversal
- `src/hummbl_clp/core/state_manager.py` -- atomic state with optimistic concurrency
- `src/hummbl_clp/core/schema_validator.py` -- stdlib JSON Schema validator
- `src/hummbl_clp/core/working_memory.py` -- ephemeral key-value store with TTL
- `src/hummbl_clp/core/__main__.py` -- CLI entry point
- `src/hummbl_clp/extensions/server.py` -- Open Brain HTTP server
- `tools/validate_repo.py` -- repo baseline validator
