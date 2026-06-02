# hummbl-clp

**CLP: Cognitive Ledger Protocol** -- Shared memory and knowledge compilation for multi-agent coordination.

[![Core Deps](https://img.shields.io/badge/core%20deps-zero-brightgreen)]()
[![Optional Extras](https://img.shields.io/badge/optional-extras-blue)]()

**Tier:** 1 — Stdlib Core + Optional Extras. Core ledger, query, and index are stdlib-only. The `[bus]` extra adds `hummbl-bus` integration.

## What This Is

CLP provides persistent, queryable shared memory for AI agent fleets. Agents write observations, decisions, and learnings to an append-only JSONL ledger. A BM25 inverted index enables fast retrieval across five memory pools. Zettelkasten-style links connect related entries.

**Extraction status: MODERATE REFACTORING** -- Core ledger logic (13 of 23 files) is self-contained and stdlib-only. Retrieval, consolidation, and boot context modules have founder-mode coupling that needs decoupling.

## Core Components (extractable now)

| Module | Purpose |
|--------|---------|
| `ledger_writer.py` | Append-only JSONL with content hashing and optimistic locking |
| `query.py` | Query engine (by agent, type, scope, tags, time range) |
| `state_manager.py` | Shared state with version-based optimistic concurrency |
| `schema_validator.py` | Stdlib-only JSON Schema validator (Draft 2020-12 subset) |
| `models.py` | Data models (LedgerEntry with Zettelkasten-style links, SharedState) |
| `indexer.py` | BM25 inverted term index (stdlib-only) |
| `verified_writer.py` | Schema-validated writes |
| `scoring_lenses.py` | Multi-lens scoring for retrieval ranking |
| `working_memory.py` | Session-scoped working memory |

## Coupled Components (need refactoring)

| Module | Coupling | Extraction Path |
|--------|----------|-----------------|
| `retriever.py` | Pulls from 5 memory pools (bus, briefings, findings, MEMORY.md) | Abstract pool interface |
| `consolidator.py` | Uses Ollama for synthesis via services pattern | Make model backend pluggable |
| `boot_context.py` | References founder_mode service registration | Decouple to config-driven boot |
| `startup_context.py` | Similar to boot_context | Same approach |
| `migration.py` | Imports from bus history and git | Make source adapters pluggable |
| `feedback_tracker.py` | Retrieval logging for stigmergic ranking | Standalone with interface |

## Structure

```
docs/                  # Placeholder for extracted protocol/reference docs
examples/              # Placeholder for runnable examples
src/hummbl_clp/core/   # Extractable core (ledger, query, state, schema, index)
src/hummbl_clp/extensions/
                       # Coupled founder-mode adapters pending decoupling
tests/                 # Placeholder for extracted test coverage
tools/                 # Repo-local validation tooling
```

## Validation

Run the repository baseline validator before opening a pull request:

```powershell
C:\Users\Owner\bin\python.cmd tools\validate_repo.py
```

Gitea CI runs the same command on pull requests and pushes to `master`.

## License

MIT
