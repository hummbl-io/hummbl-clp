# hummbl-clp

**CLP: Cognitive Ledger Protocol** -- Shared memory and knowledge compilation for multi-agent coordination. Stdlib-only Python.

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
docs/
  protocol.md          # CLP specification
  schema.md            # Ledger entry and shared state schemas
  retrieval.md         # BM25 indexing and multi-pool retrieval
  migration-guide.md   # Extracting CLP from founder-mode
src/
  core/                # Extractable core (ledger, query, state, schema, index)
  retrieval/           # Retrieval subsystem (needs refactoring)
  synthesis/           # Consolidation subsystem (needs refactoring)
tests/
examples/
```

## License

MIT
