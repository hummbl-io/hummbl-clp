# DOCTRINE.md — hummbl-clp

**Status:** v0.1
**Steward:** HUMMBL Research Institute

## 1. Thesis

hummbl-clp is the Cognitive Ledger Protocol: persistent, queryable shared
memory for multi-agent AI coordination. Agents write observations, decisions,
and learnings to an append-only JSONL ledger. A BM25 inverted index and SQLite
FTS5 index enable fast retrieval. Zettelkasten-style links connect related
entries. Content scanning rejects prompt injection, credential leakage, and
steganographic attacks before they reach the ledger or boot context.

The core bet is that shared agent memory is a library problem, not a platform
problem: the ledger, query engine, state manager, schema validator, and index
should be stdlib-only, dependency-free, and embeddable in any Python 3.11+
runtime. The library is extracted from a founder-mode production system and is
in moderate refactoring -- 13 of 23 source files are self-contained core; the
remaining extensions have coupling that needs decoupling.

Three layers compose the cognitive substrate:

1. **Shared State** (`state.json`) -- mutable snapshot of who's doing what,
   written atomically with optimistic concurrency.
2. **Shared Memory** (`ledger.jsonl`) -- append-only learning log with
   content hashing, HMAC signing, and supersedes chains.
3. **Shared Intent** (`intent.md`) -- human-authored goals and priorities.

## 2. Conceptual vocabulary

- **LedgerEntry** -- a single piece of earned understanding: a lesson, decision,
  discovery, correction, or convention. Immutable after write.
- **Supersedes chain** -- corrections to prior entries via the `supersedes`
  field. The original entry is never modified; the correction replaces it in
  `active_entries()` queries.
- **Content hash** -- SHA-256 over canonical semantic fields (agent, vendor,
  model, type, scope, content). Detects tampering without HMAC keys.
- **HMAC-SHA256 signing** -- every entry is signed with `BUS_SIGNING_SECRET`.
  Fail-closed: unsigned writes are rejected unless explicitly bypassed.
- **Content scanning** -- pre-persistence scan for prompt injection patterns,
  credential patterns, exfiltration vectors, and invisible Unicode characters.
  NFC normalization prevents homographic bypass.
- **BM25 index** -- inverted term index with stigmergic retrieval-frequency
  boosting. A derived artifact, always rebuildable from `ledger.jsonl`.
- **SQLite FTS5 index** -- relational index with full-text search, tag/scope/
  type filtering, and recursive CTE graph traversal over links and supersession
  chains. Also a derived, disposable artifact.
- **Working memory** -- ephemeral mid-session key-value store with TTL-based
  expiry and promotion to the permanent ledger.
- **Boot context** -- a frozen snapshot of state, recent learnings, and intent,
  computed once at session start and injected into agent system prompts.
- **Federation** -- remote ledger entries ingested via the Open Brain server
  `/ingest` endpoint, verified via HMAC-SHA256 signature against
  `FEDERATION_SECRET`.

## 3. Design principles

1. **Stdlib-only core.** Core modules under `src/hummbl_clp/core/` use Python
   stdlib only. Zero third-party runtime dependencies. The library is auditable
   and supply-chain-safe.
2. **Append-only, never rewrite.** The ledger is an immutable record. Knowledge
   evolves through `supersedes` links, not by editing history.
3. **Fail-closed security.** HMAC signing and server auth default to rejecting
   unsigned/unauthenticated access. Bypasses (`CLP_ALLOW_UNSIGNED`,
   `CLP_ALLOW_NO_AUTH`) are explicit and documented.
4. **Content scanning before persistence.** Poisoned content is rejected
   before it reaches the ledger or boot context. NFC normalization and a
   42-codepoint invisible-Unicode blocklist prevent bypass attacks.
5. **Derived indices are disposable.** The BM25 JSON index and SQLite FTS5
   index are rebuildable from `ledger.jsonl`. They are never a source of truth.
6. **Crash-safe writes.** State files use atomic write (temp + fsync + rename)
   with advisory file locking on both POSIX and Windows.
7. **Proven before shipped.** Core modules are extracted from founder-mode
   production only after surviving real multi-agent coordination load.

## 4. Boundaries

hummbl-clp provides the shared memory substrate; it is not an agent
orchestration platform and does not choose which agent executes a task -- that
is the control plane's job. It does not define governance primitives (that is
hummbl-governance), though it consumes HMAC signing patterns compatible with
the bus. It is Python-only. It does not run a persistent daemon by default --
the Open Brain HTTP server is an optional extension for network-accessible
search and federation. The consolidator and scoring lenses use Ollama via
urllib but degrade gracefully when Ollama is unavailable.

## 5. Open questions

- How should the retriever's 5-pool architecture be abstracted into a pluggable
  interface to complete the decoupling from founder-mode services?
- Should the consolidator's LLM backend be made pluggable beyond Ollama, and
  what is the right interface for vendor-neutral synthesis?
- How should working memory's promotion-to-ledger path integrate with
  governance receipts for auditability?
- What is the right boundary between the BM25 JSON index and the SQLite FTS5
  index -- should one replace the other, or do they serve distinct query
  patterns?
- How should federation scale beyond a single Open Brain server to a mesh of
  peer brains with conflict resolution?
