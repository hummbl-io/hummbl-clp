"""Contract tests for LedgerPool extraction (INTENT-002 Option B, PR-3)."""

from __future__ import annotations

from pathlib import Path

from hummbl_clp.core.indexer import BM25Index
from hummbl_clp.core.interfaces import MemoryPool, MemoryResult
from hummbl_clp.core.models import LedgerEntry
from hummbl_clp.extensions.retriever import LedgerPool, OpenBrainRetriever


def _write_ledger(path: Path, contents: list[str]) -> None:
    entries = [
        LedgerEntry.create(
            agent="devin",
            vendor="local",
            model="deepseek-flash",
            entry_type="discovery",
            scope="project",
            content=content,
        )
        for content in contents
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(entry.to_jsonl() for entry in entries) + "\n",
        encoding="utf-8",
    )


def test_ledger_pool_contract(tmp_path: Path) -> None:
    ledger = tmp_path / "cognition" / "ledger.jsonl"
    _write_ledger(ledger, [
        "zebra crossing knowledge for the pool test",
        "unrelated content about ships",
    ])

    pool = LedgerPool(
        index=BM25Index(), index_path=tmp_path / "cognition" / "index.json",
    )
    assert isinstance(pool, MemoryPool)
    assert pool.name == "ledger"

    pool.ensure_index(ledger_path=ledger)
    results = pool.search("zebra", limit=5)
    assert len(results) == 1
    assert type(results[0]) is MemoryResult
    assert results[0].source == "ledger"


def test_facade_default_pools_include_ledger(tmp_path: Path) -> None:
    retriever = OpenBrainRetriever(state_dir=tmp_path)
    ledger_pool = retriever.pools["ledger"]
    assert isinstance(ledger_pool, LedgerPool)

    retriever.mark_index_loaded()
    assert ledger_pool._index_loaded is True


def test_facade_ledger_search_loads_saved_index(tmp_path: Path) -> None:
    cognition = tmp_path / "cognition"
    ledger = cognition / "ledger.jsonl"
    _write_ledger(ledger, ["zebra discovery entry"])

    # Pre-build and save the index at the path the pool loads from.
    index = BM25Index()
    index.build(ledger_path=ledger)
    index.save(cognition / "index.json")

    retriever = OpenBrainRetriever(state_dir=tmp_path)
    results = retriever.search("zebra", sources=["ledger"])

    assert len(results) == 1
    assert results[0].entry_id.startswith("clp-")
