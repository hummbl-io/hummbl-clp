# CLP Primitives — Complete Reference

**Version:** v0.1.0
**Core modules:** 13 (stdlib-only, self-contained)
**Extension modules:** 10 (coupled, pending decoupling)
**Total source files:** 23

This document is the canonical reference for all Cognitive Ledger Protocol
modules. Core modules are extractable now. Extension modules have founder-mode
coupling that needs decoupling before they can be used independently.

---

## Core modules (stdlib-only, extractable now)

| Module | File | Description |
|---|---|---|
| LedgerEntry | `core/models.py` | Frozen dataclass for append-only shared memory entries. Content hashing (SHA-256), vendor validation, tag/link normalization, supersedes chains. |
| SharedState | `core/models.py` | Mutable coordination snapshot (Layer 1). Version-based optimistic concurrency. |
| LedgerWriter | `core/ledger_writer.py` | Append-only JSONL persistence with advisory file locking (POSIX/Windows). Content scanning, HMAC-SHA256 signing, fail-closed security. |
| QueryEngine | `core/query.py` | Filtered queries, supersedes-chain resolution, boot context summarization. |
| StateManager | `core/state_manager.py` | Atomic JSON state read/write with optimistic concurrency. File claiming, agent status updates. |
| SchemaValidator | `core/schema_validator.py` | Stdlib-only JSON Schema validator (Draft 2020-12 subset). Validates ledger entries and shared state. |
| BM25Index | `core/indexer.py` | BM25 inverted term index with stigmergic retrieval-frequency boosting. Crash-safe save (temp + fsync + rename). |
| SQLiteIndexer | `core/sqlite_indexer.py` | SQLite WAL index with FTS5 full-text search, tag/scope/type filtering, and recursive CTE graph traversal. |
| VerifiedWriter | `core/verified_writer.py` | Schema-validated writes with environment-resolved agent identity and required evidence. |
| ScoringLenses | `core/scoring_lenses.py` | Swappable analytical prompts for experiment data. 4 built-in lenses (convergence, efficiency, risk, transfer). Ollama via urllib. |
| WorkingMemory | `core/working_memory.py` | Ephemeral mid-session key-value store with TTL-based expiry, namespace enforcement, and promotion to permanent ledger. |
| ContentScanner | `core/ledger_writer.py` (`scan_content`) | Pre-persistence scan: prompt injection, credential leakage, exfiltration vectors, invisible Unicode (42 codepoints). NFC normalization. |
| CLI | `core/__main__.py` | Command-line interface: post, post-verified, query, search, graph, reindex, validate, state, boot. |

## Extension modules (coupled, pending decoupling)

| Module | File | Coupling | Extraction Path |
|---|---|---|---|
| Retriever | `extensions/retriever.py` | Pulls from 5 memory pools (bus, briefings, findings, MEMORY.md) | Abstract pool interface |
| Consolidator | `extensions/consolidator.py` | Uses Ollama for synthesis via services pattern | Make model backend pluggable |
| BootContext | `extensions/boot_context.py` | References founder-mode service registration | Decouple to config-driven boot |
| StartupContext | `extensions/startup_context.py` | Similar to boot_context; reads coordination bus | Same approach |
| Migration | `extensions/migration.py` | Imports from bus history and git | Make source adapters pluggable |
| FeedbackTracker | `extensions/feedback_tracker.py` | Retrieval logging for stigmergic ranking | Standalone with interface |
| OpenBrainServer | `extensions/server.py` | HTTP server (stdlib) with federation, auth, consolidation | Already mostly standalone; couples to retriever/consolidator |
| OpenBrainClient | `extensions/client.py` | HTTP client for remote brain queries | Standalone (stdlib only) |
| AgentHubBridge | `extensions/agenthub_bridge.py` | Bidirectional sync between coordination bus and AgentHub | Standalone (stdlib only) |
| AutoresearchBridge | `extensions/autoresearch_bridge.py` | Ingests findings from autoresearch reports into Open Brain | Standalone (stdlib only) |
| ResearchProcessor | `extensions/research_processor.py` | Local LLM research queue processor; ingests into Open Brain | Standalone (stdlib only) |

## Data models

### LedgerEntry fields

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | str | yes | `clp-<12 hex chars>` |
| `timestamp` | str | yes | ISO 8601 UTC with Z suffix |
| `agent` | str | yes | Agent identifier |
| `vendor` | str | yes | One of: anthropic, openai, google, moonshot, local, human |
| `model` | str | yes | Model identifier |
| `type` | str | yes | One of: lesson, decision, discovery, correction, convention |
| `scope` | str | yes | One of: project, module, file, convention, process |
| `content` | str | yes | Knowledge content (max 4096 chars) |
| `content_hash` | str | yes | SHA-256 hex of canonical content fields |
| `evidence` | str | no | Link to supporting artifact |
| `confidence` | float | no | 0.0–1.0 (default 0.9) |
| `supersedes` | str | no | ID of entry this corrects |
| `tags` | tuple[str, ...] | no | Categorization tags (max 10) |
| `assurance_level` | str | no | SELF, PEER, or VERIFIED |
| `signature` | str | no | HMAC-SHA256 hex |
| `links` | tuple[str, ...] | no | Related entry IDs (max 20, Zettelkasten-style) |

### SharedState fields

| Field | Type | Description |
|---|---|---|
| `version` | int | Optimistic concurrency version |
| `updated_at` | str | ISO 8601 UTC |
| `updated_by` | str | Agent that last updated |
| `active_agents` | dict | Agent ID → status info |
| `claimed_files` | dict | Filepath → claim info |
| `active_decisions` | list | Active decision records |
| `sprint` | dict | Sprint metadata |
| `flags` | dict | Feature flags |

## Content scanning categories

| Category | Patterns | Description |
|---|---|---|
| `prompt_injection` | 8 regex patterns | "ignore previous instructions", "system prompt override", etc. |
| `credential_leak` | 9 regex patterns | OpenAI keys, Anthropic keys, GitHub PATs, Slack tokens, AWS keys, PEM keys |
| `exfiltration` | 3 regex patterns | curl/wget with credential variables |
| `invisible_unicode` | 42 codepoints | Zero-width chars, bidi controls, unusual whitespace, variation selectors |

## CLI commands

| Command | Description |
|---|---|
| `post` | Write a new ledger entry |
| `post-verified` | Write a verified entry with evidence + confidence |
| `query` | Query ledger with filters |
| `search` | FTS5 full-text search over SQLite index |
| `graph` | Traverse relational links and supersedes chains |
| `reindex` | Rebuild BM25 and SQLite indices from ledger |
| `validate` | Validate ledger integrity (hashes, signatures) |
| `state` | Show current shared state |
| `boot` | Generate boot context for agent injection |

## Environment variables

| Variable | Purpose |
|---|---|
| `COGNITION_LEDGER` | Override ledger.jsonl path |
| `COGNITION_STATE` | Override state.json path |
| `COGNITION_INDEX` | Override BM25 index path |
| `COGNITION_INDEX_DB` | Override SQLite index path |
| `COGNITION_WORKING_MEMORY` | Override working memory store path |
| `COGNITION_RETRIEVAL_LOG` | Override retrieval log path |
| `COGNITION_DIR` | Override cognition directory |
| `BUS_SIGNING_SECRET` | HMAC-SHA256 signing secret (32+ bytes) |
| `FEDERATION_SECRET` | Federation verification secret (falls back to BUS_SIGNING_SECRET) |
| `CLP_ALLOW_UNSIGNED` | Bypass fail-closed signing (tests/dev only) |
| `CLP_ALLOW_NO_AUTH` | Bypass server auth fail-closed (tests/dev only) |
| `CLP_KILL_SWITCH_ENGAGED` | Kill switch for consolidator and research processor |
| `OPEN_BRAIN_TOKEN` | Bearer token for Open Brain server auth |
| `OPEN_BRAIN_URL` | Open Brain server URL (client) |
| `OLLAMA_URL` | Ollama base URL (default: http://127.0.0.1:11434) |
