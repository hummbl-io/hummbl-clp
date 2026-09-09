# CONSTITUTION.md — hummbl-clp

**Status:** v0.1
**Steward:** HUMMBL Research Institute
**Approving human:** Reuben Bowlby
**Standard:** HUMMBL Repo Standard v0.1
**Source of record:** git

## 1. Identity

`hummbl-io/hummbl-clp` — Cognitive Ledger Protocol: shared memory and knowledge compilation for multi-agent coordination. Append-only JSONL ledger with BM25 inverted index, SQLite FTS5 search, Zettelkasten-style links, HMAC-SHA256 signing, and content scanning. Stdlib-only core (13 of 23 files self-contained); coupled founder-mode adapters pending decoupling.

- **Class:** library
- **Visibility:** public
- **License:** Apache-2.0
- **Validation:** `C:\Users\Owner\bin\python.cmd tools\validate_repo.py`

## 2. Scope

This constitution operates under the HUMMBL Repo Standard (`hummbl-io/hummbl-governance/docs/standards/HUMMBL_REPO_STANDARD.md`) and the operating-environment constitution on the host machine. This constitution may be stricter than both, never weaker.

## 3. Protected invariants

These invariants are constitutionally protected. They cannot be changed, weakened, or conditionally suspended without a constitutional amendment (§7), a KRINEIA receipt, and human approval.

1. **Zero third-party runtime dependencies in core.** The core modules under `src/hummbl_clp/core/` use Python stdlib only. The `dependencies` list in `pyproject.toml` is empty. The `[bus]` extra adds `hummbl-bus` for extension modules only. Adding a third-party runtime dependency to core is a constitutional violation.
2. **Append-only ledger.** The cognitive ledger (`ledger.jsonl`) is append-only. No operator or agent may modify, delete, or rewrite existing entries. Corrections are made via `supersedes` links, not by editing prior entries.
3. **Content integrity.** Every ledger entry carries a SHA-256 `content_hash` over its canonical semantic fields. Entries with mismatched hashes are rejected at write time and flagged by `validate_integrity`.
4. **HMAC signing (fail-closed).** Ledger entries must be HMAC-SHA256 signed. When no signing secret is available, writes are rejected unless `CLP_ALLOW_UNSIGNED=1` is set (tests/dev only). The prior fail-open default is closed.
5. **Content scanning before persistence.** All content flowing into the ledger is scanned for prompt injection, credential leakage, exfiltration vectors, and invisible Unicode characters. Poisoned content is rejected before it reaches the ledger or boot context.
6. **Federation signature verification.** Remote entries ingested via the Open Brain server `/ingest` endpoint must carry a valid HMAC-SHA256 signature verified against `FEDERATION_SECRET` (or `BUS_SIGNING_SECRET`). Unsigned or invalid-signature entries are rejected.
7. **Server auth (fail-closed).** The Open Brain HTTP server rejects all authenticated endpoints with 401 when no `OPEN_BRAIN_TOKEN` is configured, unless `CLP_ALLOW_NO_AUTH=1` is set (tests/dev only).
8. **Crash-safe writes.** State files are written atomically (temp + fsync + rename). Advisory file locking (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows) prevents concurrent writer corruption.
9. **Apache-2.0 license.** The license is Apache-2.0, unchanged. No proprietary license may be introduced.
10. **Derived index disposability.** The BM25 JSON index and SQLite FTS5 index are derived artifacts, always rebuildable from `ledger.jsonl`. They are never a source of truth.

## 4. Normative files

The following files are normative. Edits require steward review:

- `CONSTITUTION.md`
- `KRINEIA.md`
- `AGENTS.md`
- `CLAUDE.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `pyproject.toml`
- `tools/validate_repo.py`

## 5. Authority

- **Steward:** HUMMBL Research Institute
- **Approving human:** Reuben Bowlby
- **Agent operating contract:** `AGENTS.md`
- **Receipt manifest:** `KRINEIA.md`

## 6. Receipt-triggering changes

The following changes require a KRINEIA receipt before admission:

- Any edit to `CONSTITUTION.md`, `KRINEIA.md`, or `pyproject.toml`
- Any change to a protected invariant (Section 3)
- Any change to the HMAC signing or content-scanning contract
- Any change to the federation or server-auth contract
- Any change to the ledger entry data model (`models.py`) that breaks serialization compatibility
- Any release or version bump
- Any change to `pyproject.toml` that alters the dependency contract

## 7. Amendment

Changes to this constitution require: a PR, a KRINEIA receipt, and human approval (Reuben Bowlby). Breaking changes bump this constitution's version (SemVer) and trigger a fleet re-audit of all repos consuming this repo's outputs.
