"""Unit tests for Tier 1 SQLite WAL indexer (relational + FTS5 + recursive graph traversal)."""
import tempfile
from pathlib import Path
from hummbl_clp.core.models import LedgerEntry, compute_content_hash
from hummbl_clp.core.sqlite_indexer import build_sqlite_index, search_entries, traverse_graph

def test_sqlite_indexer_lifecycle_and_traversal():
    """Verify build, FTS5 search, and recursive graph traversal in SQLite indexer."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ledger_file = tmp_path / "ledger.jsonl"
        db_file = tmp_path / "index.db"

        # Create 3 linked entries (clp-1 -> clp-2 -> clp-3)
        entries = []
        for i, (eid, links, supersedes, content, tag) in enumerate([
            ("clp-111111111111", ("clp-222222222222",), None, "Root architecture decision on memory systems", "architecture"),
            ("clp-222222222222", ("clp-333333333333",), None, "Derived SQLite index implementation", "database"),
            ("clp-333333333333", (), "clp-222222222222", "Superseded index schema with FTS5", "fts5"),
        ], start=1):
            e = LedgerEntry(
                id=eid,
                timestamp=f"2026-08-31T12:0{i}:00Z",
                agent="gemini (agent)",
                vendor="google",
                model="gemini-3.7-flash",
                type="decision",
                scope="project",
                content=content,
                content_hash=compute_content_hash(
                    agent="gemini (agent)",
                    vendor="google",
                    model="gemini-3.7-flash",
                    entry_type="decision",
                    scope="project",
                    content=content
                ),
                confidence=0.9,
                tags=(tag,),
                links=links,
                supersedes=supersedes,
            )
            entries.append(e)

        with open(ledger_file, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(e.to_jsonl() + "\n")

        # 1. Build Index
        count = build_sqlite_index(ledger_path=ledger_file, db_path=db_file)
        assert count == 3
        assert db_file.exists()

        # 2. Search FTS5
        res_arch = search_entries("architecture", db_path=db_file)
        assert len(res_arch) == 1
        assert res_arch[0]["id"] == "clp-111111111111"
        assert "architecture" in res_arch[0]["tags"]

        # Search with Tag Filter
        res_tag = search_entries("", tags=["fts5"], db_path=db_file)
        assert len(res_tag) == 1
        assert res_tag[0]["id"] == "clp-333333333333"

        # 3. Recursive Graph Traversal
        chain = traverse_graph("clp-111111111111", db_path=db_file, max_depth=5)
        assert len(chain) == 2
        # Depth 1: clp-1 -> clp-2
        assert chain[0]["from_id"] == "clp-111111111111"
        assert chain[0]["to_id"] == "clp-222222222222"
        assert chain[0]["depth"] == 1
        # Depth 2: clp-2 -> clp-3
        assert chain[1]["from_id"] == "clp-222222222222"
        assert chain[1]["to_id"] == "clp-333333333333"
        assert chain[1]["depth"] == 2
