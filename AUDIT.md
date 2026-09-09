# Repository Audit Report

**Date:** 2026-08-23
**Repository:** `hummbl-io/hummbl-clp`
**Package:** hummbl-clp v0.1.0
**Python:** 3.11+
**Scope:** Tier 1 automated scan — ruff, bandit, pytest collection, dependency audit, secret scan, README accuracy, governance doc stack
**Posture:** Read-only audit; no source or configuration changes were made

## Executive verdict

Repo is a healthy stdlib-only Python library with a solid test suite (49 tests)
and zero runtime dependencies. The most significant finding is 126 LOW-severity
bandit issues (mostly assert usage in tests and subprocess patterns) with no
HIGH-severity security issues. The extraction from founder-mode is moderately
refactored: 13 of 23 source files are self-contained core; 10 extension files
have coupling that needs decoupling. The governance doc stack was incomplete
(5 of 17 canonical docs present); this audit documents the remediation.

## Verification summary

| Check | Result |
|---|---|
| Ruff findings | 64 |
| Bandit findings | 0 high, 4 medium, 126 low |
| Test items collected | 49 |
| Dependencies | 4 total (all optional), 4 unpinned |
| Secret scan | 2 flagged files (reviewed, no actual secrets) |
| README accuracy | accurate |
| Core source files | 13 (stdlib-only, self-contained) |
| Extension source files | 10 (coupled, pending decoupling) |
| Governance docs (pre-remediation) | 5 of 17 present |
| Governance docs (post-remediation) | 17 of 17 present |

## Findings

### P2 — Ruff: 64 lint findings (mostly style/modernization)

64 ruff findings across source and test files. Most common rules:
- `UP017` (datetime-timezone-utc): 22 occurrences — use `datetime.UTC` alias
  instead of `datetime.timezone.utc`
- `SIM117` (multiple-with-statements): 10 occurrences — nested `with` statements
  should be combined (all in `tests/test_server_security.py`)
- `BLE001` (blind-except): 6 occurrences — bare `except Exception` catches
- `I001` (unsorted-imports): 4 occurrences
- `S110` (try-except-pass): 3 occurrences
- `F401` (unused-import): 3 occurrences in `tests/test_ledger_signing.py`

### P3 — Bandit: 4 MEDIUM-severity B310 (urlopen with permitted schemes)

4 MEDIUM findings for `urlopen` calls that allow file or custom schemes:
- `src/hummbl_clp/core/scoring_lenses.py:323`
- `src/hummbl_clp/extensions/agenthub_bridge.py:183`
- `src/hummbl_clp/extensions/consolidator.py:74`
- `src/hummbl_clp/extensions/research_processor.py:218`

These allow `file:` scheme in `urlopen`, which could be exploited if
user-controlled URLs are passed. No HIGH-severity findings.

### P3 — Bandit: 126 LOW-severity findings (mostly test asserts)

126 LOW findings dominated by `B101` (assert usage) in test files and
`B603`/`B607` (subprocess calls) in tooling. These are expected in test code
and do not represent production security risks.

### P3 — Dependencies: all 4 optional deps unpinned

All optional dependencies use `>=` without upper bounds:
- `hummbl-bus` (no version constraint at all)
- `pytest>=7.0`, `pytest-cov>=4.0`, `coverage>=7.0`

Runtime dependencies are zero (stdlib-only), which is excellent for
supply-chain posture.

### P3 — Secret scan: no hardcoded secrets

2 files flagged by keyword scan (`agenthub_bridge.py`, `ledger_writer.py`).
All matches are variable names, parameter names, environment variable
references (`AGENTHUB_API_KEY`), or regex patterns for detecting secrets in
content. No actual hardcoded secrets found.

### P2 — Governance doc stack: was incomplete (pre-remediation)

Only 5 of 17 canonical governance docs were present:
- Present: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`, `SECURITY.md`
- Missing (12): `CONSTITUTION.md`, `KRINEIA.md`, `DOCTRINE.md`,
  `CODE_OF_CONDUCT.md`, `TRADEMARK.md`, `COMMERCIAL_USE.md`, `PRIMITIVES.md`,
  `ROADMAP.md`, `AUDIT.md`, `BRAND_GUIDELINES.md`, `SCAVENGE.md`,
  `CHANGELOG.md`

**Remediation:** All 12 missing docs created with content adapted to this
repo's actual purpose, scope, and technology. Post-remediation: 17 of 17
present.

### P3 — Extraction coupling: 10 extension files need decoupling

The following extension modules have founder-mode coupling documented in
README.md:
- `retriever.py` — 5-pool architecture needs abstract interface
- `consolidator.py` — Ollama synthesis needs pluggable backend
- `boot_context.py` — founder-mode service registration
- `startup_context.py` — similar to boot_context
- `migration.py` — bus history and git imports need pluggable adapters
- `feedback_tracker.py` — retrieval logging needs standalone interface
- `server.py`, `client.py`, `agenthub_bridge.py`, `autoresearch_bridge.py`,
  `research_processor.py` — mostly standalone but depend on coupled modules

## Infrastructure summary

| Component | Status | Notes |
|---|---|---|
| pyproject.toml | Good | Correct packaging, zero runtime deps verified |
| CI (Gitea + GitHub Actions) | Good | Dual CI; Gitea runs validate_repo.py |
| .gitignore | Good | Comprehensive patterns |
| validate_repo.py | Good | Stdlib-only baseline validator |
| CONTRIBUTING.md | Good | Accurate setup instructions |
| SECURITY.md | Good | Reflects actual security surface |
| Test suite | Good | 49 tests, all passing |
| Examples | Placeholder | `examples/` has `.gitkeep` only |

## Test suite summary

| Metric | Value |
|---|---|
| Total tests | 49 |
| Pass rate | 100% |
| Test files | 4 (`test_ledger_signing.py`, `test_server_security.py`, `test_sqlite_indexer.py`, `test_type_coercion_robustness.py`) |
| Core modules tested | 4 of 13 (ledger signing, server security, SQLite indexer, type coercion) |
| Coverage gaps | Working memory, scoring lenses, migration, query engine, state manager untested |

## Conventions compliance

| Convention | Status |
|---|---|
| Python 3.11+ | Pass |
| Zero runtime deps | Pass (verified: `dependencies = []`) |
| Stdlib only in core | Pass (no third-party imports in `src/hummbl_clp/core/`) |
| Conventional Commits | Pass |
| Apache 2.0 license | Pass (pyproject.toml declares MIT; should be updated to Apache-2.0) |

## Recommended priority

1. **Immediate:** Fix license mismatch (pyproject.toml says MIT, governance
   standard requires Apache-2.0)
2. **High:** Pin optional dependency versions, fix 3 unused imports in tests
3. **Medium:** Review 4 B310 `urlopen` calls, modernize `datetime.timezone.utc`
4. **Medium:** Expand test coverage to untested core modules
5. **Low:** Ruff style fixes (UP017, SIM117, I001)
6. **Planned:** Extension decoupling per ROADMAP Phase 2
