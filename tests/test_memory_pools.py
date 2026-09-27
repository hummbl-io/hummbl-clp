"""Contract tests for MemoryPool extraction (INTENT-002 Option B, PR-2).

Verifies that the bus/briefings text pool, findings pool, and MEMORY.md
pool implement ``core.interfaces.MemoryPool`` and that the
``OpenBrainRetriever`` facade composes injected pools (fan-out, sources
filtering, token-budget truncation preserved).
"""

from __future__ import annotations

import json
from pathlib import Path

from hummbl_clp.core.interfaces import MemoryPool, MemoryResult
from hummbl_clp.extensions.retriever import (
    FindingsPool,
    MemoryMdPool,
    OpenBrainRetriever,
    TextFilePool,
)


def test_text_file_pool_contract(tmp_path: Path) -> None:
    coordination = tmp_path / "coordination"
    coordination.mkdir(parents=True)
    (coordination / "messages.tsv").write_text(
        "2026-09-27T00:00:00Z\tdevin\tall\tSTATUS\tzebra alpha\n"
        "2026-09-27T01:00:00Z\tdevin\tall\tSTATUS\tzebra beta\n",
        encoding="utf-8",
    )
    pool = TextFilePool(
        name="bus", search_dir=coordination, glob_pattern="*.tsv",
    )
    assert isinstance(pool, MemoryPool)
    assert pool.name == "bus"

    results = pool.search("zebra", limit=1)
    assert len(results) == 1
    assert type(results[0]) is MemoryResult

    # since filters TSV lines before scoring
    results = pool.search("zebra", since="2026-09-27T00:30:00Z")
    assert len(results) == 1


def test_findings_pool_contract(tmp_path: Path) -> None:
    findings_dir = tmp_path / "autoresearch"
    findings_dir.mkdir(parents=True)
    (findings_dir / "findings_a.json").write_text(
        json.dumps([
            {
                "id": "f1",
                "claim": "zebra crossing claim",
                "source": "s",
                "confidence": 0.9,
                "category": "c",
            },
        ]),
        encoding="utf-8",
    )
    pool = FindingsPool(findings_dir=findings_dir)
    assert isinstance(pool, MemoryPool)
    assert pool.name == "findings"

    results = pool.search("zebra")
    assert len(results) == 1
    assert type(results[0]) is MemoryResult


def test_memory_md_pool_contract(tmp_path: Path) -> None:
    memory_dir = tmp_path / "projects" / "p1" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("zebra migration notes", encoding="utf-8")
    pool = MemoryMdPool(memory_dir=tmp_path / "projects")
    assert isinstance(pool, MemoryPool)
    assert pool.name == "memory_md"

    results = pool.search("zebra")
    assert len(results) == 1
    assert type(results[0]) is MemoryResult


class _StubPool(MemoryPool):
    def __init__(self, name: str, results: list[MemoryResult]) -> None:
        self._name = name
        self._results = results
        self.calls: list[dict[str, object]] = []

    @property
    def name(self) -> str:
        return self._name

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        since: str | None = None,
        **kwargs: object,
    ) -> list[MemoryResult]:
        self.calls.append({"query": query, "limit": limit, "since": since})
        return self._results


def test_facade_fans_out_only_to_selected_sources(tmp_path: Path) -> None:
    pool_a = _StubPool(
        "a", [MemoryResult(source="a", entry_id="a:1", score=0.9, content="x", tokens=10)]
    )
    pool_b = _StubPool(
        "b", [MemoryResult(source="b", entry_id="b:1", score=0.8, content="y", tokens=10)]
    )
    retriever = OpenBrainRetriever(state_dir=tmp_path, pools=[pool_a, pool_b])

    results = retriever.search("q", sources=["a"])

    assert [r.source for r in results] == ["a"]
    assert len(pool_a.calls) == 1
    assert len(pool_b.calls) == 0


def test_facade_token_budget_truncation_preserved(tmp_path: Path) -> None:
    pool_a = _StubPool("a", [
        MemoryResult(source="a", entry_id="a:1", score=0.9, content="A" * 400, tokens=100),
        MemoryResult(source="a", entry_id="a:2", score=0.5, content="B" * 400, tokens=100),
    ])
    retriever = OpenBrainRetriever(state_dir=tmp_path, pools=[pool_a])

    results = retriever.search("q", sources=["a"], token_budget=150)

    assert len(results) == 2
    assert results[0].tokens == 100
    assert results[1].tokens == 50
    assert results[1].content.endswith("...")
