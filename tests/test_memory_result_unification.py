"""Contract tests for MemoryResult unification (INTENT-002 Option B, PR-1).

The OpenBrain extension layer previously defined its own ``MemoryResult``.
PR-1 deletes that class in favor of ``hummbl_clp.core.interfaces.MemoryResult``
while preserving the serialized HTTP contract (``to_dict`` includes
``tokens`` and rounds ``score`` to 4dp).
"""

from __future__ import annotations

from pathlib import Path

from hummbl_clp.core.interfaces import MemoryResult
from hummbl_clp.extensions import retriever as retriever_module
from hummbl_clp.extensions.retriever import OpenBrainRetriever, _estimate_tokens


def test_extension_retriever_exposes_core_memory_result() -> None:
    """The extension module must resolve MemoryResult to the core class."""
    assert retriever_module.MemoryResult is MemoryResult


def test_to_dict_includes_tokens_and_rounds_score() -> None:
    result = MemoryResult(
        source="bus",
        entry_id="bus:messages.tsv",
        score=0.123456,
        content="hello world",
        tokens=7,
    )
    assert result.to_dict() == {
        "source": "bus",
        "entry_id": "bus:messages.tsv",
        "score": 0.1235,
        "content": "hello world",
        "metadata": {},
        "tokens": 7,
    }


def test_text_pool_results_carry_estimated_tokens(tmp_path: Path) -> None:
    coordination = tmp_path / "coordination"
    coordination.mkdir(parents=True)
    (coordination / "messages.tsv").write_text(
        "2026-09-27T00:00:00Z\tdevin\tall\tSTATUS\tnothing to see here\n"
        "2026-09-27T00:01:00Z\tdevin\tall\tSTATUS\tzebra crossing signal ahead\n",
        encoding="utf-8",
    )

    retriever = OpenBrainRetriever(state_dir=tmp_path)
    results = retriever.search("zebra", sources=["bus"])

    assert results, "expected one bus hit for 'zebra'"
    result = results[0]
    assert type(result) is MemoryResult
    assert result.tokens == _estimate_tokens(result.content)
