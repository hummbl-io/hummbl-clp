"""Open Brain Retriever -- unified search across all memory pools.

Queries ledger index, bus digests, briefings, autoresearch findings,
and MEMORY.md. Returns ranked results within a token budget.

This is the primary query interface for the Open Brain.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from hummbl_clp.extensions.feedback_tracker import log_retrieval
from hummbl_clp.core.indexer import BM25Index, tokenize

logger = logging.getLogger(__name__)

# Approximate tokens per character (conservative estimate for English)
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _resolve_state_dir(override: str | Path | None = None) -> Path:
    """Resolve the state directory."""
    if override:
        return Path(override)
    env_path = os.environ.get("CLP_STATE_DIR")
    if env_path:
        return Path(env_path)
    try:
        import subprocess
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if root:
            return Path(root) / "_state"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path("_state")


class MemoryResult:
    """A single result from the Open Brain retriever."""

    __slots__ = ("source", "entry_id", "score", "content", "metadata", "tokens")

    def __init__(
        self,
        *,
        source: str,
        entry_id: str,
        score: float,
        content: str,
        metadata: dict[str, Any],
        tokens: int = 0,
    ) -> None:
        self.source = source
        self.entry_id = entry_id
        self.score = score
        self.content = content
        self.metadata = metadata
        self.tokens = tokens or _estimate_tokens(content)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "entry_id": self.entry_id,
            "score": round(self.score, 4),
            "content": self.content,
            "metadata": self.metadata,
            "tokens": self.tokens,
        }


class OpenBrainRetriever:
    """Unified retriever across all memory pools.

    Memory pools:
      1. Cognitive Ledger (ledger.jsonl via BM25 index)
      2. Bus digests (configurable directory)
      3. Briefings (configurable directory)
      4. Autoresearch findings (configurable directory)
      5. MEMORY.md (Claude Code auto-memory)
    """

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        index: BM25Index | None = None,
    ) -> None:
        self.state_dir = _resolve_state_dir(state_dir)
        self.index = index or BM25Index()
        self._index_loaded = False

    def ensure_index(self, ledger_path: str | Path | None = None) -> None:
        """Load or build the index."""
        if self._index_loaded:
            return
        index_path = self.state_dir / "cognition" / "index.json"
        if not self.index.load(index_path):
            self.index.build(ledger_path)
            try:
                self.index.save(index_path)
            except OSError as e:
                logger.warning("Could not save index: %s", e)
        self._index_loaded = True

    def search(
        self,
        query: str,
        *,
        token_budget: int = 2000,
        scope: str | None = None,
        entry_type: str | None = None,
        since: str | None = None,
        sources: list[str] | None = None,
        agent: str = "unknown",
        limit: int = 50,
    ) -> list[MemoryResult]:
        """Search all memory pools and return ranked results within token budget.

        Parameters
        ----------
        query : str
            Natural language query.
        token_budget : int
            Maximum estimated tokens in returned results.
        scope : str | None
            Filter ledger entries by scope.
        entry_type : str | None
            Filter ledger entries by type.
        since : str | None
            ISO timestamp -- only return entries after this time.
        sources : list[str] | None
            Which memory pools to search. Default: all.
            Options: "ledger", "bus", "briefings", "findings", "memory_md"
        agent : str
            Agent making the query (for feedback tracking).
        limit : int
            Maximum number of results before budget filtering.

        Returns
        -------
        list[MemoryResult]
            Ranked results within token budget.
        """
        all_sources = sources or [
            "ledger", "bus", "briefings", "findings", "memory_md",
        ]

        results: list[MemoryResult] = []

        if "ledger" in all_sources:
            results.extend(self._search_ledger(
                query, scope=scope, entry_type=entry_type,
                since=since, limit=limit,
            ))

        if "bus" in all_sources:
            results.extend(self._search_text_pool(
                query, pool_name="bus",
                search_dir=self.state_dir / "coordination",
                glob_pattern="*.tsv",
                since=since, limit=limit // 4,
            ))

        if "briefings" in all_sources:
            results.extend(self._search_text_pool(
                query, pool_name="briefings",
                search_dir=self.state_dir.parent / "state" / "briefings",
                glob_pattern="*.md",
                since=since, limit=limit // 4,
            ))

        if "findings" in all_sources:
            results.extend(self._search_findings(
                query, since=since, limit=limit // 4,
            ))

        if "memory_md" in all_sources:
            results.extend(self._search_memory_md(query, limit=limit // 4))

        # Sort all results by score
        results.sort(key=lambda r: r.score, reverse=True)

        # Apply token budget
        budgeted: list[MemoryResult] = []
        remaining = token_budget
        for result in results:
            if result.tokens <= remaining:
                budgeted.append(result)
                remaining -= result.tokens
            elif remaining > 0:
                # Truncate content to fit remaining budget
                chars = remaining * _CHARS_PER_TOKEN
                truncated = MemoryResult(
                    source=result.source,
                    entry_id=result.entry_id,
                    score=result.score,
                    content=result.content[:chars] + "...",
                    metadata=result.metadata,
                    tokens=remaining,
                )
                budgeted.append(truncated)
                remaining = 0
                break

        # Log retrieval for feedback tracking
        retrieved_ids = [r.entry_id for r in budgeted if r.entry_id.startswith("clp-")]
        if retrieved_ids:
            try:
                log_retrieval(
                    query=query,
                    entry_ids=retrieved_ids,
                    agent=agent,
                    log_path=self.state_dir / "cognition" / "retrieval_log.jsonl",
                )
                # Update index retrieval counts
                for eid in retrieved_ids:
                    self.index.record_retrieval(eid)
            except OSError:
                pass  # Non-critical

        return budgeted

    def _search_ledger(
        self,
        query: str,
        *,
        scope: str | None = None,
        entry_type: str | None = None,
        since: str | None = None,
        limit: int = 20,
    ) -> list[MemoryResult]:
        """Search the cognitive ledger via BM25 index."""
        self.ensure_index()

        hits = self.index.search(
            query, limit=limit, scope=scope,
            entry_type=entry_type, since=since,
        )

        results = []
        for hit in hits:
            meta = hit["meta"]
            results.append(MemoryResult(
                source="ledger",
                entry_id=hit["id"],
                score=hit["score"],
                content=meta.get("content_preview", ""),
                metadata={
                    "type": meta.get("type"),
                    "scope": meta.get("scope"),
                    "agent": meta.get("agent"),
                    "timestamp": meta.get("timestamp"),
                    "confidence": meta.get("confidence"),
                    "tags": meta.get("tags", []),
                },
            ))
        return results

    def _search_text_pool(
        self,
        query: str,
        *,
        pool_name: str,
        search_dir: Path,
        glob_pattern: str,
        since: str | None = None,
        limit: int = 5,
    ) -> list[MemoryResult]:
        """Search a directory of text files using simple term matching."""
        if not search_dir.exists():
            return []

        query_tokens = set(tokenize(query))
        if not query_tokens:
            return []

        results = []
        try:
            files = sorted(search_dir.glob(glob_pattern), reverse=True)
        except OSError:
            return []

        for filepath in files[:20]:  # Cap file scan
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # TSV-aware: extract message column for bus files
            if filepath.suffix == ".tsv":
                text = _extract_tsv_messages(text, since=since)

            # Simple term overlap scoring
            file_tokens = set(tokenize(text[:5000]))  # Cap per file
            overlap = query_tokens & file_tokens
            if not overlap:
                continue

            score = len(overlap) / len(query_tokens)

            # Extract relevant snippet
            snippet = _extract_snippet(text, query_tokens, max_chars=500)

            results.append(MemoryResult(
                source=pool_name,
                entry_id=f"{pool_name}:{filepath.name}",
                score=score * 0.7,  # Discount vs ledger BM25
                content=snippet,
                metadata={"file": str(filepath.name)},
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _search_findings(
        self,
        query: str,
        *,
        since: str | None = None,
        limit: int = 5,
    ) -> list[MemoryResult]:
        """Search autoresearch distillation findings."""
        findings_dir = self.state_dir / "autoresearch"
        if not findings_dir.exists():
            return []

        query_tokens = set(tokenize(query))
        if not query_tokens:
            return []

        results = []
        for filepath in findings_dir.glob("findings_*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            findings = data if isinstance(data, list) else data.get("findings", [])
            for finding in findings:
                claim = finding.get("claim", "")
                tokens = set(tokenize(claim))
                overlap = query_tokens & tokens
                if not overlap:
                    continue

                score = len(overlap) / len(query_tokens) * 0.8
                results.append(MemoryResult(
                    source="findings",
                    entry_id=finding.get("id", f"finding:{filepath.name}"),
                    score=score,
                    content=claim,
                    metadata={
                        "source_file": finding.get("source", ""),
                        "confidence": finding.get("confidence", 0),
                        "category": finding.get("category", ""),
                    },
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _search_memory_md(
        self,
        query: str,
        *,
        limit: int = 3,
    ) -> list[MemoryResult]:
        """Search Claude Code MEMORY.md files."""
        memory_dir = Path.home() / ".claude" / "projects"
        if not memory_dir.exists():
            return []

        query_tokens = set(tokenize(query))
        if not query_tokens:
            return []

        results = []
        try:
            for memory_file in memory_dir.rglob("memory/*.md"):
                try:
                    text = memory_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                file_tokens = set(tokenize(text[:3000]))
                overlap = query_tokens & file_tokens
                if not overlap:
                    continue

                score = len(overlap) / len(query_tokens) * 0.6
                snippet = _extract_snippet(text, query_tokens, max_chars=300)

                results.append(MemoryResult(
                    source="memory_md",
                    entry_id=f"memory:{memory_file.name}",
                    score=score,
                    content=snippet,
                    metadata={"file": str(memory_file)},
                ))
        except OSError:
            pass

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]


def _extract_tsv_messages(
    text: str,
    *,
    since: str | None = None,
    max_lines: int = 200,
) -> str:
    r"""Extract message column from TSV bus format.

    Bus format: timestamp\tfrom\tto\ttype\tmessage
    """
    lines = text.strip().split("\n")
    lines = lines[-max_lines:]
    messages = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        ts = parts[0]
        if since and ts < since:
            continue
        messages.append(f"{parts[1]} {parts[3]} {parts[4]}")
    return "\n".join(messages)


def _extract_snippet(
    text: str,
    query_tokens: set[str],
    max_chars: int = 500,
) -> str:
    """Extract the most relevant snippet from text around query term matches."""
    text_lower = text.lower()
    best_pos = 0
    best_score = 0

    window = max_chars
    for i in range(0, min(len(text), 5000), 100):
        chunk = text_lower[i : i + window]
        chunk_tokens = set(tokenize(chunk))
        score = len(query_tokens & chunk_tokens)
        if score > best_score:
            best_score = score
            best_pos = i

    snippet = text[best_pos : best_pos + max_chars].strip()
    if best_pos > 0:
        snippet = "..." + snippet
    if best_pos + max_chars < len(text):
        snippet = snippet + "..."

    return snippet
