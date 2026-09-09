# Changelog

All notable changes to **hummbl-clp** are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- **Governance doc stack remediation** — 12 missing governance docs created to
  bring the repo to a full 17-doc stack: `CONSTITUTION.md`, `KRINEIA.md`,
  `DOCTRINE.md`, `docs/doctrine/PRIMITIVES.md`, `docs/architecture/ROADMAP.md`, `docs/audits/AUDIT.md`, `docs/research/SCAVENGE.md`,
  `docs/policy/TRADEMARK.md`, `docs/policy/COMMERCIAL_USE.md`, `docs/research/BRAND_GUIDELINES.md`,
  `CODE_OF_CONDUCT.md`, and this `CHANGELOG.md`. All content adapted to the
  repo's actual purpose, scope, and technology.

### Changed

- Updated `CLAUDE.md` with expanded architecture and command documentation for
  AI assistants.

---

## [0.1.0] — 2026-08-23

### Added

- **Core ledger engine** — append-only JSONL persistence with content hashing
  (SHA-256), HMAC-SHA256 signing (fail-closed), and content scanning (prompt
  injection, credential leakage, exfiltration vectors, invisible Unicode — 42
  codepoints with NFC normalization).
- **LedgerEntry data model** — frozen dataclass with vendor validation, tag/link
  normalization, supersedes chains, and Zettelkasten-style links.
- **SharedState data model** — mutable coordination snapshot with version-based
  optimistic concurrency.
- **Query engine** — filtered queries, supersedes-chain resolution, and boot
  context summarization.
- **State manager** — atomic JSON state read/write with file claiming and
  agent status updates. Crash-safe writes (temp + fsync + rename) with advisory
  file locking (POSIX/Windows).
- **Schema validator** — stdlib-only JSON Schema validator (Draft 2020-12
  subset).
- **BM25 index** — inverted term index with stigmergic retrieval-frequency
  boosting. Crash-safe save.
- **SQLite FTS5 index** — relational index with full-text search, tag/scope/type
  filtering, and recursive CTE graph traversal over links and supersession
  chains.
- **Verified writer** — schema-validated writes with environment-resolved agent
  identity and required evidence.
- **Scoring lenses** — 4 built-in analytical lenses (convergence, efficiency,
  risk, transfer) for experiment data analysis via Ollama.
- **Working memory** — ephemeral mid-session key-value store with TTL-based
  expiry, namespace enforcement, and promotion to permanent ledger.
- **CLI** — `hummbl-clp` entry point with commands: post, post-verified, query,
  search, graph, reindex, validate, state, boot.
- **Open Brain server** — stdlib HTTP server with search, federation (HMAC
  signature verification), consolidation, and fail-closed auth.
- **Open Brain client** — stdlib HTTP client for remote brain queries.
- **AgentHub bridge** — bidirectional sync between coordination bus and
  AgentHub.
- **Autoresearch bridge** — ingests findings from autoresearch reports into
  Open Brain.
- **Research processor** — local LLM research queue processor with Ollama.
- **Migration tools** — import from MEMORY.md, bus history, and git log.
  Idempotent with deterministic IDs.
- **Content scanning** — 8 prompt injection patterns, 9 credential patterns,
  3 exfiltration patterns, 42 invisible Unicode codepoints. NFC normalization
  prevents homographic bypass.
- **Federation** — remote entry ingestion with HMAC-SHA256 signature
  verification against `FEDERATION_SECRET`.
- **Repository baseline validator** — `tools/validate_repo.py` (stdlib-only).
- **Test suite** — 49 tests covering ledger signing, server security, SQLite
  indexer, and type coercion robustness.
- **Zero third-party runtime dependencies** — stdlib only in core.
- Apache-2.0 license.

### Known issues

- 10 extension modules have founder-mode coupling pending decoupling (see
<<<<<<< HEAD
  README.md and docs/architecture/ROADMAP.md).
=======
  README.md and ROADMAP.md).
>>>>>>> 2b2ae1e (docs: add canonical governance doc stack (17/17))
- 64 ruff lint findings (mostly style/modernization).
- Optional dependencies unpinned.
- License field in `pyproject.toml` says MIT; governance standard requires
  Apache-2.0.

---

[0.1.0]: https://github.com/hummbl-io/hummbl-clp/releases/tag/v0.1.0
