"""Cognitive Ledger query engine.

Provides filtered queries, supersedes-chain resolution, and boot context
summarization for the append-only ledger.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from hummbl_clp.core.ledger_writer import read_entries
from hummbl_clp.core.models import LedgerEntry, LedgerEntryType, LedgerScope


def query_entries(
    *,
    ledger_path: str | Path | None = None,
    entry_type: str | LedgerEntryType | None = None,
    scope: str | LedgerScope | None = None,
    agent: str | None = None,
    since: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
) -> list[LedgerEntry]:
    """Query ledger entries with filters.

    Thin wrapper around read_entries with additional query semantics.
    """
    return read_entries(
        ledger_path=ledger_path,
        entry_type=entry_type,
        scope=scope,
        agent=agent,
        since=since,
        tags=tags,
        limit=limit,
    )


def active_entries(
    *,
    ledger_path: str | Path | None = None,
    limit: int = 200,
) -> list[LedgerEntry]:
    """Return entries that have not been superseded by corrections.

    Entries with a `supersedes` field pointing to another entry's ID
    effectively replace that entry. This function filters out superseded
    entries, returning only the current active knowledge.
    """
    all_entries = read_entries(ledger_path=ledger_path, limit=limit)

    # Collect all superseded IDs
    superseded_ids: set[str] = set()
    for entry in all_entries:
        if entry.supersedes:
            superseded_ids.add(entry.supersedes)

    # Filter out superseded entries
    return [e for e in all_entries if e.id not in superseded_ids]


def latest_by_scope(
    *,
    ledger_path: str | Path | None = None,
    limit: int = 500,
) -> dict[str, LedgerEntry]:
    """Return the most recent active entry per scope.

    Handles supersedes chains: if a correction supersedes an earlier entry,
    the correction wins. Returns a dict mapping scope value to entry.
    """
    entries = active_entries(ledger_path=ledger_path, limit=limit)
    result: dict[str, LedgerEntry] = {}
    for entry in entries:
        if entry.scope not in result:
            result[entry.scope] = entry
    return result


def summarize_for_boot(
    *,
    ledger_path: str | Path | None = None,
    max_entries: int = 20,
    max_age_days: int = 14,
) -> str:
    """Produce a compact text summary suitable for agent context injection.

    Returns a markdown-formatted summary of recent active ledger entries,
    prioritizing lessons and decisions.
    """
    # Calculate since timestamp
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    since = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = active_entries(ledger_path=ledger_path, limit=max_entries * 2)

    # Filter by age
    entries = [e for e in entries if e.timestamp >= since]

    # Prioritize: decisions > corrections > lessons > conventions > discoveries
    priority = {
        "decision": 0,
        "correction": 1,
        "lesson": 2,
        "convention": 3,
        "discovery": 4,
    }
    entries.sort(key=lambda e: (priority.get(e.type, 5), e.timestamp))

    # Limit
    entries = entries[:max_entries]

    if not entries:
        return "No recent learnings."

    lines: list[str] = []
    for entry in entries:
        prefix = entry.type.upper()
        tags_str = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(
            f"- [{entry.timestamp[:10]}] ({entry.agent}) "
            f"{prefix}: {entry.content[:200]}{tags_str}"
        )

    return "\n".join(lines)
