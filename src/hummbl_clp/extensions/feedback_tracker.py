"""Open Brain Feedback Tracker -- log which memories were retrieved per session.

Append-only JSONL log of retrieval events. Feeds into stigmergic ranking
so frequently-useful memories gain weight over time.

Storage: _state/cognition/retrieval_log.jsonl
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None

try:
    import msvcrt  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = "_state/cognition/retrieval_log.jsonl"
_WINDOWS_LOCK_SPAN = 1


def _lock_file(file_obj) -> None:
    """Acquire an exclusive advisory lock for the current file object."""
    if fcntl is not None:
        fcntl.flock(file_obj, fcntl.LOCK_EX)
        return
    if msvcrt is not None:
        file_obj.flush()
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, _WINDOWS_LOCK_SPAN)
        return
    logger.warning("No advisory file locking backend available; proceeding unlocked")


def _unlock_file(file_obj) -> None:
    """Release the advisory lock for the current file object."""
    if fcntl is not None:
        fcntl.flock(file_obj, fcntl.LOCK_UN)
        return
    if msvcrt is not None:
        file_obj.flush()
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, _WINDOWS_LOCK_SPAN)
        return


def _resolve_log_path(override: str | Path | None = None) -> Path:
    """Resolve the retrieval log file path."""
    if override:
        return Path(override)
    env_path = os.environ.get("COGNITION_RETRIEVAL_LOG")
    if env_path:
        return Path(env_path)
    try:
        import subprocess
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if root:
            return Path(root) / DEFAULT_LOG_PATH
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path(DEFAULT_LOG_PATH)


def log_retrieval(
    *,
    query: str,
    entry_ids: list[str],
    agent: str = "unknown",
    session_id: str = "",
    log_path: str | Path | None = None,
) -> None:
    """Log a retrieval event (which entries were returned for a query)."""
    path = _resolve_log_path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": agent,
        "query": query[:500],  # Truncate long queries
        "entry_ids": entry_ids[:50],  # Cap at 50 entries
        "count": len(entry_ids),
    }
    if session_id:
        event["session_id"] = session_id

    line = json.dumps(event, separators=(",", ":")) + "\n"

    with open(path, "a", encoding="utf-8") as f:
        _lock_file(f)
        try:
            f.write(line)
            f.flush()
        finally:
            _unlock_file(f)


def get_retrieval_counts(
    *,
    log_path: str | Path | None = None,
    since: str | None = None,
) -> dict[str, int]:
    """Aggregate retrieval counts per entry ID from the log."""
    path = _resolve_log_path(log_path)
    if not path.exists():
        return {}

    counts: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since and event.get("timestamp", "") < since:
                    continue
                for entry_id in event.get("entry_ids", []):
                    counts[entry_id] = counts.get(entry_id, 0) + 1
    except OSError as e:
        logger.warning("Failed to read retrieval log: %s", e)

    return counts


def read_retrieval_log(
    *,
    log_path: str | Path | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read recent retrieval events from the log."""
    path = _resolve_log_path(log_path)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning("Failed to read retrieval log: %s", e)
        return []

    # Return most recent first
    return events[-limit:][::-1]
