# hummbl-clp Roadmap

This document outlines the strategic direction and technical evolution of
the **hummbl-clp** library, the Cognitive Ledger Protocol for multi-agent
shared memory.

---

## Current Status: v0.1.0 (Extraction & Decoupling)

**Focus:** Stdlib-only core extraction from founder-mode, with staged
decoupling of coupled extension modules.

- ✅ **Core ledger engine** — append-only JSONL, content hashing, HMAC-SHA256
  signing, content scanning (prompt injection, credentials, exfiltration,
  invisible Unicode).
- ✅ **Query engine** — filtered queries, supersedes-chain resolution, boot
  context summarization.
- ✅ **State manager** — atomic JSON state with optimistic concurrency, file
  claiming, agent status.
- ✅ **Schema validator** — stdlib-only JSON Schema (Draft 2020-12 subset).
- ✅ **BM25 index** — inverted term index with stigmergic retrieval boosting.
- ✅ **SQLite FTS5 index** — relational index with full-text search, tag/scope
  filtering, recursive CTE graph traversal.
- ✅ **Working memory** — ephemeral key-value store with TTL, namespace
  enforcement, promotion to ledger.
- ✅ **Scoring lenses** — 4 built-in analytical lenses for experiment data.
- ✅ **CLI** — post, post-verified, query, search, graph, reindex, validate,
  state, boot.
- ✅ **Open Brain server** — HTTP server with search, federation, consolidation,
  fail-closed auth.
- ✅ **Migration tools** — import from MEMORY.md, bus history, git log.
- ✅ **Zero third-party runtime dependencies** — stdlib only in core.

### Extraction status: MODERATE REFACTORING

13 of 23 source files are self-contained core. 10 extension files have
founder-mode coupling that needs decoupling.

---

## Phase 1: Core Stabilization (v0.1.x)

**Focus:** Harden the extracted core and stabilize the public API.

- [ ] Pin optional dependency versions (`hummbl-bus`, `pytest`, `pytest-cov`)
- [ ] Fix 64 ruff lint findings (UP017 datetime.UTC, SIM117 nested with, BLE001
      blind-except, I001 unsorted imports)
- [ ] Review 4 B310 bandit `urlopen` calls in extensions for `file:` scheme
      exposure
- [ ] Add upper-bound version pins to all optional dependencies
- [ ] Expand test coverage from 49 tests to cover all core modules
- [ ] Document the public API surface and mark it stable

---

## Phase 2: Extension Decoupling (v0.2.0)

**Focus:** Decouple the 6 coupled extension modules from founder-mode services.

- [ ] **Retriever** — abstract the 5-pool architecture into a pluggable
      interface so memory pools (bus, briefings, findings, MEMORY.md) can be
      added without core changes.
- [ ] **Consolidator** — make the LLM backend pluggable beyond Ollama. Define
      a `SynthesisBackend` protocol so other providers can be swapped in.
- [ ] **Boot context** — decouple from founder-mode service registration to
      config-driven boot.
- [ ] **Startup context** — same approach as boot_context; make bus path
      configurable without founder-mode imports.
- [ ] **Migration** — make source adapters pluggable so import sources (bus,
      git, MEMORY.md) can be extended without core changes.
- [ ] **Feedback tracker** — make standalone with a clean interface for
      stigmergic ranking input.

---

## Phase 3: Federation & Network (v0.3.0)

**Focus:** Production-grade federation for multi-brain coordination.

- [ ] Peer-to-peer brain mesh with conflict resolution
- [ ] Federation batch verification with Merkle anchoring
- [ ] Open Brain server TLS support and production deployment guide
- [ ] Rate limiting and request validation hardening
- [ ] Federation replay and backfill support

---

## Phase 4: Advanced Retrieval (v0.4.0)

**Focus:** Smarter retrieval and knowledge compilation.

- [ ] Semantic similarity beyond BM25 term overlap (e.g., embedding-based
      retrieval via pluggable backend)
- [ ] Consolidation scheduling with configurable frequency and group size
- [ ] Working memory → ledger promotion with governance receipts
- [ ] Multi-agent knowledge conflict detection and resolution
- [ ] Boot context personalization per agent role

---

## Phase 5: Production Maturity (v1.0.0)

**Focus:** API stability guarantee and production readiness.

- [ ] Formal API stability guarantee (SemVer)
- [ ] Complete documentation with usage examples
- [ ] Performance benchmarks for large ledgers (100K+ entries)
- [ ] Python 3.14 CI support
- [ ] Stress testing under high-concurrency multi-agent load

---

_Copyright 2026 HUMMBL, LLC. All rights reserved._
