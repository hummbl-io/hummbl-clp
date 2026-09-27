# hummbl-clp

**CLP: Cognitive Ledger Protocol** — Shared memory and knowledge compilation engine for multi-agent coordination.

[![PyPI version](https://img.shields.io/pypi/v/hummbl-clp.svg)](https://pypi.org/project/hummbl-clp/)
[![Python versions](https://img.shields.io/pypi/pyversions/hummbl-clp.svg)](https://pypi.org/project/hummbl-clp/)
[![Core Deps](https://img.shields.io/badge/core%20deps-zero-brightgreen)](https://pypi.org/project/hummbl-clp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Overview

The **Cognitive Ledger Protocol (CLP)** provides cryptographically verifiable, queryable shared memory for AI agent fleets. Agents append structured observations, decisions, hypotheses, and learnings to an append-only JSONL ledger.

- **Zero Runtime Dependencies**: Core ledger, query engine, schema validation, and BM25 indexer are 100% Python standard library (`json`, `hashlib`, `math`, `dataclasses`, `pathlib`).
- **Cryptographic Provenance**: Every entry computes a deterministic SHA-256 content hash with optional HMAC signing for federation.
- **Relational Memory Graphs**: Native Zettelkasten-style relational links (`links` field) connect observations, decisions, and outcomes.
- **Multi-Pool Search**: BM25 inverted index ranking across memory pools.
- **Optimistic Concurrency**: Version-tracked shared state management with optimistic locking.

---

## Installation

```bash
pip install hummbl-clp
```

For optional bus integration:
```bash
pip install "hummbl-clp[bus]"
```

---

## Quick Start

### 1. Appending to the Ledger

```python
from hummbl_clp.core.models import LedgerEntry, LedgerScope
from hummbl_clp.core.ledger_writer import post_entry

# Append a verified observation
entry = post_entry(
    agent="my-agent",
    scope=LedgerScope.SESSION,
    title="Service Architecture Verification",
    content="All 131 tests verified green in sealed virtual environment.",
    tags=["audit", "verification", "milestone"],
    path="my_ledger.jsonl",
    allow_unsigned=True,  # Set to False when CL_SIGNING_SECRET is configured
)

print(f"Recorded entry {entry.id}")
print(f"Content SHA-256: {entry.content_hash}")
```

### 2. Querying Entries

```python
from hummbl_clp.core.query import query_entries

# Query entries by agent and tags
results = query_entries(
    path="my_ledger.jsonl",
    agent="my-agent",
    tags=["verification"],
)

for item in results:
    print(f"[{item.timestamp}] {item.title}: {item.content}")
```

---

## Architecture & Modules

```
src/hummbl_clp/
├── core/
│   ├── models.py           # LedgerEntry, SharedState, and type schemas
│   ├── ledger_writer.py    # Append-only JSONL with SHA-256 hashing & flock locking
│   ├── query.py            # Query engine (by agent, scope, tags, time range)
│   ├── indexer.py          # BM25 inverted term index (stdlib-only)
│   ├── state_manager.py    # Concurrency-controlled shared state
│   ├── schema_validator.py # Draft 2020-12 JSON Schema validation subset
│   └── working_memory.py   # Ephemeral session-scoped working memory
└── extensions/
    ├── retriever.py        # Multi-pool memory retrieval interface
    └── memory_pools.py     # Pluggable memory storage adapters
```

---

## Running Tests

The test suite runs with standard `pytest` or Python stdlib `unittest`:

```bash
# Clone the repository
git clone https://github.com/hummbl-io/hummbl-clp.git
cd hummbl-clp

# Install test dependencies
pip install pytest

# Run tests
pytest tests/ -v
```

All 131 unit and security tests pass with 0 external dependencies on the core library.

---

## License

This project is licensed under the [MIT License](LICENSE).
