"""Tier 1 SQLite WAL Index for Cognitive Ledger Protocol (stdlib-only).

Provides relational and FTS5 search indexing over ledger.jsonl.
The SQLite database is a derived, disposable artifact (rebuildable from ledger.jsonl).
Features:
- FTS5 full-text search
- Fast exact tag, scope, and type filtering
- Recursive CTE graph traversal over declared links and supersession chains (WITH RECURSIVE)
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hummbl_clp.core.ledger_writer import read_entries

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_INDEX_PATH = "_state/cognition/index.db"


def _resolve_db_path(override: str | Path | None = None) -> Path:
    """Resolve the SQLite index file path."""
    if override:
        return Path(override)
    env_path = os.environ.get("COGNITION_INDEX_DB")
    if env_path:
        return Path(env_path)
    try:
        import subprocess
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if root:
            p = Path(root) / DEFAULT_SQLITE_INDEX_PATH
            if p.exists() or p.parent.exists():
                return p
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    home_p = Path.home() / DEFAULT_SQLITE_INDEX_PATH
    if home_p.exists():
        return home_p

    return Path(DEFAULT_SQLITE_INDEX_PATH)


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Connect to SQLite database with WAL mode and foreign keys enabled."""
    db_file = _resolve_db_path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize relational and FTS5 schema for Tier 1 index."""
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            agent TEXT NOT NULL,
            vendor TEXT NOT NULL,
            model TEXT NOT NULL,
            type TEXT NOT NULL,
            scope TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            confidence REAL NOT NULL,
            supersedes TEXT,
            evidence TEXT,
            signature TEXT,
            assurance_level TEXT
        );

        CREATE TABLE IF NOT EXISTS tags (
            entry_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
            PRIMARY KEY (entry_id, tag)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

        CREATE TABLE IF NOT EXISTS links (
            src TEXT NOT NULL,
            dst TEXT NOT NULL,
            kind TEXT NOT NULL,
            FOREIGN KEY (src) REFERENCES entries(id) ON DELETE CASCADE,
            PRIMARY KEY (src, dst, kind)
        );
        CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst);

        CREATE VIRTUAL TABLE IF NOT EXISTS fts_entries USING fts5(
            id UNINDEXED,
            content,
            tags,
            agent,
            tokenize = 'porter unicode61'
        );
        """)


def build_sqlite_index(
    ledger_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Rebuild SQLite index from ledger.jsonl. Returns count of indexed entries."""
    db_file = _resolve_db_path(db_path)
    entries = read_entries(ledger_path=ledger_path, limit=999_999)

    conn = _get_connection(db_file)
    init_schema(conn)

    with conn:
        conn.execute("DELETE FROM fts_entries;")
        conn.execute("DELETE FROM links;")
        conn.execute("DELETE FROM tags;")
        conn.execute("DELETE FROM entries;")

        for e in entries:
            conn.execute("""
            INSERT INTO entries (
                id, timestamp, agent, vendor, model, type, scope,
                content, content_hash, confidence, supersedes, evidence, signature, assurance_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                e.id, e.timestamp, e.agent, e.vendor, e.model, e.type, e.scope,
                e.content, e.content_hash, e.confidence, e.supersedes, e.evidence, e.signature, e.assurance_level
            ))

            for tag in e.tags:
                conn.execute("INSERT OR IGNORE INTO tags (entry_id, tag) VALUES (?, ?);", (e.id, tag))

            for link in e.links:
                conn.execute("INSERT OR IGNORE INTO links (src, dst, kind) VALUES (?, ?, ?);", (e.id, link, "link"))

            if e.supersedes:
                conn.execute("INSERT OR IGNORE INTO links (src, dst, kind) VALUES (?, ?, ?);", (e.id, e.supersedes, "supersedes"))

            conn.execute("""
            INSERT INTO fts_entries (id, content, tags, agent) VALUES (?, ?, ?, ?);
            """, (e.id, e.content, " ".join(e.tags), e.agent))

    conn.close()
    logger.info("Built SQLite index at %s with %d entries", db_file, len(entries))
    return len(entries)


def index_single_entry(
    entry: Any,
    db_path: str | Path | None = None,
) -> None:
    """Incrementally index a single LedgerEntry into the SQLite index."""
    db_file = _resolve_db_path(db_path)
    conn = _get_connection(db_file)
    init_schema(conn)

    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO entries (
            id, timestamp, agent, vendor, model, type, scope,
            content, content_hash, confidence, supersedes, evidence, signature, assurance_level
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            entry.id, entry.timestamp, entry.agent, entry.vendor, entry.model, entry.type, entry.scope,
            entry.content, entry.content_hash, entry.confidence, entry.supersedes, entry.evidence, entry.signature, entry.assurance_level
        ))

        for tag in entry.tags:
            conn.execute("INSERT OR IGNORE INTO tags (entry_id, tag) VALUES (?, ?);", (entry.id, tag))

        for link in entry.links:
            conn.execute("INSERT OR IGNORE INTO links (src, dst, kind) VALUES (?, ?, ?);", (entry.id, link, "link"))

        if entry.supersedes:
            conn.execute("INSERT OR IGNORE INTO links (src, dst, kind) VALUES (?, ?, ?);", (entry.id, entry.supersedes, "supersedes"))

        # FTS5 insert or replace
        conn.execute("DELETE FROM fts_entries WHERE id = ?;", (entry.id,))
        conn.execute("""
        INSERT INTO fts_entries (id, content, tags, agent) VALUES (?, ?, ?, ?);
        """, (entry.id, entry.content, " ".join(entry.tags), entry.agent))

    conn.close()


def search_entries(
    query: str,
    *,
    db_path: str | Path | None = None,
    tags: Optional[List[str]] = None,
    scope: Optional[str] = None,
    entry_type: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search ledger using FTS5 full-text search with metadata filters."""
    db_file = _resolve_db_path(db_path)
    if not db_file.exists():
        return []

    conn = _get_connection(db_file)
    conditions = ["1=1"]
    params: List[Any] = []

    if query.strip():
        # Clean query for FTS5 match
        clean_q = '"' + query.replace('"', '""').strip() + '"'
        conditions.append("e.id IN (SELECT id FROM fts_entries WHERE fts_entries MATCH ?)")
        params.append(clean_q)

    if scope:
        conditions.append("e.scope = ?")
        params.append(scope.lower())

    if entry_type:
        conditions.append("e.type = ?")
        params.append(entry_type.lower())

    if since:
        conditions.append("e.timestamp >= ?")
        params.append(since)

    if tags:
        for t in tags:
            conditions.append("e.id IN (SELECT entry_id FROM tags WHERE tag = ?)")
            params.append(t.lower())

    where_clause = " AND ".join(conditions)
    sql = f"""
    SELECT e.*, GROUP_CONCAT(DISTINCT t.tag) as tags_concat
    FROM entries e
    LEFT JOIN tags t ON e.id = t.entry_id
    WHERE {where_clause}
    GROUP BY e.id
    ORDER BY e.timestamp DESC
    LIMIT ?;
    """
    params.append(limit)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    results = []
    for r in rows:
        row_dict = dict(r)
        raw_tags = row_dict.pop("tags_concat")
        row_dict["tags"] = raw_tags.split(",") if raw_tags else []
        results.append(row_dict)

    conn.close()
    return results


def traverse_graph(
    root_id: str,
    *,
    db_path: str | Path | None = None,
    max_depth: int = 5,
) -> List[Dict[str, Any]]:
    """Traverse declared links and supersession chains using SQLite WITH RECURSIVE CTE."""
    db_file = _resolve_db_path(db_path)
    if not db_file.exists():
        return []

    conn = _get_connection(db_file)
    sql = """
    WITH RECURSIVE chain(id, dst, kind, depth, path) AS (
        SELECT src, dst, kind, 1, src || '->' || dst
        FROM links
        WHERE src = ?
        UNION
        SELECT l.src, l.dst, l.kind, c.depth + 1, c.path || '->' || l.dst
        FROM links l
        JOIN chain c ON l.src = c.dst
        WHERE c.depth < ? AND instr(c.path, l.dst) = 0
    )
    SELECT c.id as from_id, c.dst as to_id, c.kind, c.depth, c.path, e.type, e.content
    FROM chain c
    LEFT JOIN entries e ON c.dst = e.id
    ORDER BY c.depth ASC;
    """
    cursor = conn.execute(sql, (root_id, max_depth))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows
