# SCAVENGE.md — hummbl-clp

## Status

**Active.** This repo is the Cognitive Ledger Protocol extraction lane and is
under active development. It is not archived and not in scavenger mode.

The core ledger engine (13 of 23 source files) is self-contained and
stdlib-only. Extension modules are being decoupled from founder-mode services
per `docs/architecture/ROADMAP.md`.

## What to extract from here

If scavenging this repo for components to use elsewhere:

1. **Core ledger engine** (`src/hummbl_clp/core/`) — append-only JSONL writer
   with content hashing, HMAC signing, content scanning, and advisory file
   locking. Fully self-contained, stdlib-only.
2. **BM25 index** (`core/indexer.py`) — inverted term index with stigmergic
   ranking. No dependencies.
3. **SQLite FTS5 index** (`core/sqlite_indexer.py`) — relational index with
   full-text search and recursive CTE graph traversal. Stdlib `sqlite3` only.
4. **Schema validator** (`core/schema_validator.py`) — JSON Schema Draft 2020-12
   subset. No dependencies.
5. **Working memory** (`core/working_memory.py`) — ephemeral key-value store
   with TTL and promotion to ledger. No dependencies.
6. **Content scanner** (`core/ledger_writer.py:scan_content`) — prompt
   injection, credential, exfiltration, and invisible Unicode detection. No
   dependencies.

## What NOT to extract

- `extensions/retriever.py` — coupled to 5 memory pools (bus, briefings,
  findings, MEMORY.md) via founder-mode paths. Needs abstraction first.
- `extensions/consolidator.py` — coupled to Ollama service pattern. Needs
  pluggable backend interface first.
- `extensions/boot_context.py` / `startup_context.py` — reference founder-mode
  service registration. Needs config-driven decoupling first.
