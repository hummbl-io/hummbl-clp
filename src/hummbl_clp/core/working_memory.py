"""CLP Working Memory -- ephemeral mid-session state for multi-agent coordination.

Provides a mutable key-value store with TTL-based expiry, namespace enforcement,
and promotion to the permanent cognitive ledger. Designed for structured
intermediate state (hypotheses, open questions, in-progress findings) that is
visible to concurrent agents but ephemeral by default.

Uses atomic write (temp + fsync + rename) and fcntl.flock for crash safety
and concurrent writer safety, matching state_manager.py patterns.

Stdlib-only -- no third-party dependencies.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

from hummbl_clp.core.ledger_writer import (
    ContentScanError,  # noqa: F401 — re-exported for tests
    scan_content as _scan_content,
)

logger = logging.getLogger(__name__)

# Default store location (relative to repo root)
DEFAULT_STORE_PATH = "_state/cognition/working_memory.json"

# Max items to prevent unbounded growth
MAX_ITEMS = 100

# Max content length (matches ledger's 4096 char limit)
MAX_CONTENT_LENGTH = 4096

# Max TTL: 24 hours in seconds
MAX_TTL_SECONDS = 86400

# Max tags per item
MAX_TAGS = 5

# Key pattern: simplified agent name, colon, topic
# Agent names: alphanumeric, hyphens, underscores
# Topics: alphanumeric, hyphens, underscores, dots
_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+:[a-zA-Z0-9_.-]+$")

# Content scanning imported from ledger_writer (hardened: 42-char Unicode
# blocklist + NFC normalization). See ledger_writer.scan_content().


class ConcurrencyError(Exception):
    """Raised when optimistic concurrency check fails."""


def _scan_value(value: Any) -> None:
    """Recursively scan a JSON-serializable value for dangerous content."""
    if isinstance(value, str):
        _scan_content(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            _scan_content(k)
            _scan_value(v)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _scan_value(item)


def _utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp."""
    # Handle Z suffix
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _is_expired(item: dict[str, Any]) -> bool:
    """Check if a working memory item is expired."""
    ttl = item.get("ttl_seconds", 3600)
    if ttl == 0:
        return False
    expires_utc = item.get("expires_utc", "")
    if not expires_utc:
        return False
    try:
        expires = _parse_iso(expires_utc)
        return datetime.now(timezone.utc) >= expires
    except (ValueError, TypeError):
        return False


def _extract_namespace(key: str) -> str:
    """Extract the agent namespace prefix from a key."""
    if ":" not in key:
        raise ValueError(f"Key must contain ':' separator: {key!r}")
    return key.split(":", 1)[0]


def _resolve_store_path(override: str | Path | None = None) -> Path:
    """Resolve the working memory store file path."""
    if override:
        return Path(override)
    env_path = os.environ.get("COGNITION_WORKING_MEMORY")
    if env_path:
        return Path(env_path)
    try:
        import subprocess
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if root:
            return Path(root) / DEFAULT_STORE_PATH
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path(DEFAULT_STORE_PATH)


@dataclass
class WorkingMemoryItem:
    """A single item in working memory."""

    key: str
    value: Any  # JSON-serializable
    agent: str
    created_utc: str
    expires_utc: str
    metadata: dict[str, Any] = field(default_factory=dict)
    promoted_to: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        d: dict[str, Any] = {
            "key": self.key,
            "value": self.value,
            "agent": self.agent,
            "created_utc": self.created_utc,
            "expires_utc": self.expires_utc,
            "version": self.version,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        if self.promoted_to is not None:
            d["promoted_to"] = self.promoted_to
        # Compute ttl_seconds for schema compatibility
        try:
            created = _parse_iso(self.created_utc)
            expires = _parse_iso(self.expires_utc)
            ttl = int((expires - created).total_seconds())
            d["ttl_seconds"] = max(ttl, 0)
        except (ValueError, TypeError):
            d["ttl_seconds"] = 3600
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkingMemoryItem:
        """Deserialize from dictionary."""
        return cls(
            key=data["key"],
            value=data["value"],
            agent=data["agent"],
            created_utc=data["created_utc"],
            expires_utc=data["expires_utc"],
            metadata=data.get("metadata", {}),
            promoted_to=data.get("promoted_to"),
            version=data.get("version", 1),
        )


class WorkingMemoryStore:
    """Ephemeral mid-session state store for multi-agent coordination.

    Stores key-value items with TTL-based expiry and namespace enforcement.
    Items can be promoted to the permanent cognitive ledger when mature.

    Thread-safe via fcntl.flock. Crash-safe via atomic writes.
    """

    def __init__(self, store_path: str | Path | None = None) -> None:
        self._path = _resolve_store_path(store_path)
        self._lock_path = self._path.with_suffix(".lock")

    @property
    def path(self) -> Path:
        """Return the store file path."""
        return self._path

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _read_store(self) -> dict[str, Any]:
        """Read the store file. Returns empty store structure if missing/corrupt."""
        if not self._path.exists():
            return self._empty_store()
        try:
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                return self._empty_store()
            data = json.loads(text)
            if not isinstance(data, dict) or "items" not in data:
                return self._empty_store()
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse working memory file %s: %s", self._path, e)
            return self._empty_store()

    def _empty_store(self) -> dict[str, Any]:
        """Return an empty store structure."""
        now = _utc_now_iso()
        return {
            "version": 0,
            "session_id": str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "updated_by": "",
            "items": {},
        }

    def _atomic_write(self, store: dict[str, Any]) -> None:
        """Write store atomically: temp file + fsync + rename. Caller holds lock."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        try:
            content = json.dumps(store, indent=2, sort_keys=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        # Harden permissions
        try:
            current_mode = self._path.stat().st_mode & 0o777
            if current_mode != 0o600:
                self._path.chmod(0o600)
        except OSError:
            pass

    def _locked_write(self, modify_fn) -> dict[str, Any]:
        """Read-modify-write under exclusive lock."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "a") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            elif msvcrt is not None:
                lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                store = self._read_store()
                store = modify_fn(store)
                self._atomic_write(store)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                elif msvcrt is not None:
                    lock_file.flush()
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(
        self,
        key: str,
        value: Any,
        agent: str,
        ttl_seconds: int = 3600,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> WorkingMemoryItem:
        """Write or update a working memory item.

        Parameters
        ----------
        key : str
            Namespaced key in format "agent_namespace:topic".
        value : Any
            JSON-serializable value.
        agent : str
            Agent identifier writing the item.
        ttl_seconds : int
            Time-to-live in seconds. 0 = no expiry. Default 3600 (1 hour).
        metadata : dict | None
            Optional metadata dict.
        expected_version : int | None
            If provided, the write fails if the store version doesn't match.

        Returns:
        -------
        WorkingMemoryItem
            The item as written.

        Raises:
        ------
        ValueError
            If key format invalid, namespace mismatch, or content too large.
        ContentScanError
            If value contains injection/credential patterns.
        ConcurrencyError
            If expected_version doesn't match.
        """
        # Validate key format
        if not _KEY_PATTERN.match(key):
            raise ValueError(
                f"Invalid key format: {key!r}. "
                "Expected pattern: agent_namespace:topic "
                "(alphanumeric, hyphens, underscores, dots)"
            )

        # Validate namespace matches agent
        namespace = _extract_namespace(key)
        if namespace != agent:
            raise ValueError(
                f"Namespace mismatch: key namespace {namespace!r} "
                f"does not match agent {agent!r}"
            )

        # Validate TTL
        if ttl_seconds < 0:
            raise ValueError(f"ttl_seconds must be >= 0, got {ttl_seconds}")
        if ttl_seconds > MAX_TTL_SECONDS:
            raise ValueError(
                f"ttl_seconds must be <= {MAX_TTL_SECONDS} (24 hours), "
                f"got {ttl_seconds}"
            )

        # Validate content length for string values
        if isinstance(value, str) and len(value) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Value too long: {len(value)} chars "
                f"(max {MAX_CONTENT_LENGTH})"
            )

        # Validate metadata
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a dict")

        # Content scanning
        _scan_value(value)
        if metadata:
            _scan_value(metadata)

        # Ensure value is JSON-serializable
        try:
            json.dumps(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Value is not JSON-serializable: {e}") from e

        now = _utc_now_iso()
        now_dt = datetime.now(timezone.utc)
        if ttl_seconds == 0:
            # No expiry -- set to far future
            expires_utc = (now_dt + timedelta(days=365 * 100)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        else:
            expires_utc = (now_dt + timedelta(seconds=ttl_seconds)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        result_item: list[WorkingMemoryItem] = []

        def _modify(store: dict[str, Any]) -> dict[str, Any]:
            # Concurrency check
            if expected_version is not None and store["version"] != expected_version:
                raise ConcurrencyError(
                    f"Version mismatch: expected {expected_version}, "
                    f"found {store['version']}"
                )

            items = store["items"]

            # Check max items (only for new keys)
            if key not in items and len(items) >= MAX_ITEMS:
                raise ValueError(
                    f"Working memory full: {len(items)} items "
                    f"(max {MAX_ITEMS}). Call expire_stale() or clear()."
                )

            # Determine version for the item
            item_version = items[key].get("version", 1) + 1 if key in items else 1

            item = WorkingMemoryItem(
                key=key,
                value=value,
                agent=agent,
                created_utc=items[key]["created_utc"] if key in items else now,
                expires_utc=expires_utc,
                metadata=metadata or {},
                promoted_to=items[key].get("promoted_to") if key in items else None,
                version=item_version,
            )

            items[key] = item.to_dict()
            store["version"] += 1
            store["updated_at"] = now
            store["updated_by"] = agent
            result_item.append(item)
            return store

        self._locked_write(_modify)
        return result_item[0]

    def get(self, key: str) -> WorkingMemoryItem | None:
        """Read a single working memory item by key.

        Returns None if the key is missing or the item has expired.
        """
        store = self._read_store()
        items = store.get("items", {})
        if key not in items:
            return None
        item_data = items[key]
        if _is_expired(item_data):
            return None
        return WorkingMemoryItem.from_dict(item_data)

    def get_all(self, agent: str | None = None) -> list[WorkingMemoryItem]:
        """List all non-expired items, optionally filtered by agent namespace.

        Parameters
        ----------
        agent : str | None
            If provided, only return items owned by this agent.
        """
        store = self._read_store()
        items = store.get("items", {})
        result = []
        for item_data in items.values():
            if _is_expired(item_data):
                continue
            if agent is not None and item_data.get("agent") != agent:
                continue
            result.append(WorkingMemoryItem.from_dict(item_data))
        return result

    def delete(self, key: str, agent: str) -> None:
        """Remove a working memory item. Only the owning agent can delete.

        Parameters
        ----------
        key : str
            The key to delete.
        agent : str
            The agent requesting deletion (must own the item).

        Raises:
        ------
        ValueError
            If the item doesn't exist or agent doesn't own it.
        """
        def _modify(store: dict[str, Any]) -> dict[str, Any]:
            items = store["items"]
            if key not in items:
                raise ValueError(f"Key not found: {key!r}")
            if items[key].get("agent") != agent:
                raise ValueError(
                    f"Cannot delete {key!r}: owned by "
                    f"{items[key].get('agent')!r}, not {agent!r}"
                )
            del items[key]
            store["version"] += 1
            store["updated_at"] = _utc_now_iso()
            store["updated_by"] = agent
            return store

        self._locked_write(_modify)

    def expire_stale(self) -> int:
        """Remove all items past their TTL.

        Returns the number of items removed.
        """
        removed_count: list[int] = [0]

        def _modify(store: dict[str, Any]) -> dict[str, Any]:
            items = store["items"]
            expired_keys = [k for k, v in items.items() if _is_expired(v)]
            for k in expired_keys:
                del items[k]
            removed_count[0] = len(expired_keys)
            if expired_keys:
                store["version"] += 1
                store["updated_at"] = _utc_now_iso()
                store["updated_by"] = "system"
            return store

        self._locked_write(_modify)
        return removed_count[0]

    def promote_to_ledger(self, key: str, agent: str) -> dict[str, Any]:
        """Graduate a working memory item to a LedgerEntry.

        Does NOT import ledger_writer directly. Returns a dict that callers
        can pass to ledger_writer.post_entry() after constructing a LedgerEntry.

        The working memory item is marked with the promoted_to field set to
        a generated CLP entry ID.

        Parameters
        ----------
        key : str
            The key to promote.
        agent : str
            The agent requesting promotion (must own the item).

        Returns:
        -------
        dict
            A dict with fields suitable for constructing a LedgerEntry:
            {entry_id, agent, content, created_utc, metadata, key}.

        Raises:
        ------
        ValueError
            If item not found, not owned by agent, or already promoted.
        """
        entry_id = f"clp-{uuid.uuid4().hex[:12]}"
        result: list[dict[str, Any]] = []

        def _modify(store: dict[str, Any]) -> dict[str, Any]:
            items = store["items"]
            if key not in items:
                raise ValueError(f"Key not found: {key!r}")
            item_data = items[key]
            if item_data.get("agent") != agent:
                raise ValueError(
                    f"Cannot promote {key!r}: owned by "
                    f"{item_data.get('agent')!r}, not {agent!r}"
                )
            if item_data.get("promoted_to") is not None:
                raise ValueError(
                    f"Item {key!r} already promoted to "
                    f"{item_data['promoted_to']!r}"
                )

            # Mark as promoted
            items[key]["promoted_to"] = entry_id
            items[key]["version"] = items[key].get("version", 1) + 1
            store["version"] += 1
            store["updated_at"] = _utc_now_iso()
            store["updated_by"] = agent

            # Build the return dict
            value = item_data["value"]
            content = value if isinstance(value, str) else json.dumps(value)
            result.append({
                "entry_id": entry_id,
                "agent": item_data["agent"],
                "content": content,
                "created_utc": item_data["created_utc"],
                "metadata": item_data.get("metadata", {}),
                "key": key,
            })
            return store

        self._locked_write(_modify)
        return result[0]

    def clear(self, agent: str | None = None) -> int:
        """Clear working memory items.

        Parameters
        ----------
        agent : str | None
            If provided, only clear items owned by this agent.
            If None, clear all items.

        Returns:
        -------
        int
            Number of items cleared.
        """
        cleared: list[int] = [0]

        def _modify(store: dict[str, Any]) -> dict[str, Any]:
            items = store["items"]
            if agent is None:
                cleared[0] = len(items)
                store["items"] = {}
            else:
                keys_to_remove = [
                    k for k, v in items.items()
                    if v.get("agent") == agent
                ]
                for k in keys_to_remove:
                    del items[k]
                cleared[0] = len(keys_to_remove)
            if cleared[0] > 0:
                store["version"] += 1
                store["updated_at"] = _utc_now_iso()
                store["updated_by"] = agent or "system"
            return store

        self._locked_write(_modify)
        return cleared[0]

    def stats(self) -> dict[str, Any]:
        """Return statistics about the working memory store.

        Returns:
        -------
        dict
            {count, expired_count, oldest, newest, by_agent, version, session_id}
        """
        store = self._read_store()
        items = store.get("items", {})

        count = 0
        expired_count = 0
        oldest: str | None = None
        newest: str | None = None
        by_agent: dict[str, int] = {}

        for item_data in items.values():
            if _is_expired(item_data):
                expired_count += 1
            else:
                count += 1
            agent = item_data.get("agent", "unknown")
            by_agent[agent] = by_agent.get(agent, 0) + 1
            created = item_data.get("created_utc", "")
            if created:
                if oldest is None or created < oldest:
                    oldest = created
                if newest is None or created > newest:
                    newest = created

        return {
            "count": count,
            "expired_count": expired_count,
            "oldest": oldest,
            "newest": newest,
            "by_agent": by_agent,
            "version": store.get("version", 0),
            "session_id": store.get("session_id", ""),
        }
