"""Shared State Manager -- atomic JSON state read/write with optimistic concurrency.

Layer 1 of the Cognitive Ledger: a mutable snapshot of who's doing what.
Unlike the append-only ledger, state.json is overwritten atomically.

Uses write-to-temp + fsync + os.replace for crash safety.
Uses fcntl.flock for concurrent writer safety.
Uses version field for optimistic concurrency control.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None

try:
    import msvcrt  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None

from hummbl_clp.core.models import SharedState

logger = logging.getLogger(__name__)

# Default state location
DEFAULT_STATE_PATH = "_state/cognition/state.json"
_WINDOWS_LOCK_SPAN = 1


class ConcurrencyError(Exception):
    """Raised when optimistic concurrency check fails."""


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


def _resolve_state_path(override: str | Path | None = None) -> Path:
    """Resolve state file path."""
    if override:
        return Path(override)
    env_path = os.environ.get("COGNITION_STATE")
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
            return Path(root) / DEFAULT_STATE_PATH
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path(DEFAULT_STATE_PATH)


def _read_state_from_path(path: Path) -> SharedState:
    """Read state from a resolved path. No path resolution."""
    if not path.exists():
        return SharedState()
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return SharedState.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to parse state file %s: %s", path, e)
        return SharedState()


def _atomic_write(path: Path, state: SharedState) -> None:
    """Write state atomically: temp file + fsync + replace. Caller holds lock."""
    tmp_path = path.with_suffix(".tmp")
    try:
        content = state.to_json()
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up orphaned temp file on any failure
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    # Harden permissions
    try:
        current_mode = path.stat().st_mode & 0o777
        if current_mode != 0o600:
            path.chmod(0o600)
    except OSError:
        pass


def read_state(state_path: str | Path | None = None) -> SharedState:
    """Read current shared state from JSON file.

    Returns a default empty state if the file doesn't exist.
    """
    path = _resolve_state_path(state_path)
    return _read_state_from_path(path)


def write_state(
    state: SharedState,
    *,
    state_path: str | Path | None = None,
    expected_version: int | None = None,
) -> SharedState:
    """Write shared state atomically with optimistic concurrency.

    Parameters
    ----------
    state : SharedState
        The state to write.
    state_path : str | Path | None
        Override state file path.
    expected_version : int | None
        If provided, the write will fail if the file's current version
        doesn't match. This prevents lost updates from concurrent writers.

    Returns:
    -------
    SharedState
        The state as written.

    Raises:
    ------
    ConcurrencyError
        If expected_version doesn't match the file's current version.
    """
    path = _resolve_state_path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lock_path = path.with_suffix(".lock")

    with open(lock_path, "a") as lock_file:
        _lock_file(lock_file)
        try:
            # Optimistic concurrency check -- read UNDER lock to prevent
            # lost updates (two writers both passing the version check).
            if expected_version is not None and path.exists():
                current = _read_state_from_path(path)
                if current.version != expected_version:
                    raise ConcurrencyError(
                        f"Version mismatch: expected {expected_version}, "
                        f"found {current.version}"
                    )

            _atomic_write(path, state)
        finally:
            _unlock_file(lock_file)

    return state


def _locked_read_modify_write(
    state_path: str | Path | None,
    modify_fn,
) -> SharedState:
    """Read state under lock, apply modify_fn, write back atomically.

    This is the safe pattern for all read-modify-write operations.
    modify_fn receives the current SharedState and should mutate + return it.
    Raises whatever modify_fn raises (e.g., ValueError for claim conflicts).
    """
    path = _resolve_state_path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lock_path = path.with_suffix(".lock")

    with open(lock_path, "a") as lock_file:
        _lock_file(lock_file)
        try:
            state = _read_state_from_path(path)
            state = modify_fn(state)
            _atomic_write(path, state)
        finally:
            _unlock_file(lock_file)

    return state


def claim_file(
    filepath: str,
    agent_id: str,
    *,
    purpose: str = "",
    state_path: str | Path | None = None,
) -> SharedState:
    """Register file ownership in shared state.

    Parameters
    ----------
    filepath : str
        The file being claimed.
    agent_id : str
        The agent claiming it.
    purpose : str
        Why the file is being claimed.
    state_path : str | Path | None
        Override state file path.

    Returns:
    -------
    SharedState
        Updated state.

    Raises:
    ------
    ValueError
        If the file is already claimed by a different agent.
    """

    def _modify(state: SharedState) -> SharedState:
        if filepath in state.claimed_files:
            existing = state.claimed_files[filepath]
            if existing.get("agent") != agent_id:
                raise ValueError(
                    f"{filepath} already claimed by {existing.get('agent')}"
                )

        state.claimed_files[filepath] = {
            "agent": agent_id,
            "claimed_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "purpose": purpose,
        }
        state.increment_version(agent_id)
        return state

    return _locked_read_modify_write(state_path, _modify)


def release_file(
    filepath: str,
    agent_id: str,
    *,
    state_path: str | Path | None = None,
) -> SharedState:
    """Release file ownership in shared state.

    Only the claiming agent can release a file (or force with agent_id="*").
    """

    def _modify(state: SharedState) -> SharedState:
        if filepath not in state.claimed_files:
            return state  # Nothing to release

        existing = state.claimed_files[filepath]
        if agent_id != "*" and existing.get("agent") != agent_id:
            raise ValueError(
                f"Cannot release {filepath}: claimed by "
                f"{existing.get('agent')}, not {agent_id}"
            )

        del state.claimed_files[filepath]
        state.increment_version(agent_id)
        return state

    return _locked_read_modify_write(state_path, _modify)


def update_agent_status(
    agent_id: str,
    status: str,
    *,
    vendor: str | None = None,
    model: str | None = None,
    capabilities: list[str] | None = None,
    state_path: str | Path | None = None,
) -> SharedState:
    """Update agent presence in shared state."""

    def _modify(state: SharedState) -> SharedState:
        agent_info: dict = state.active_agents.get(agent_id, {})
        agent_info["status"] = status
        agent_info["last_seen"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        if vendor is not None:
            agent_info["vendor"] = vendor
        if model is not None:
            agent_info["model"] = model
        if capabilities is not None:
            agent_info["capabilities"] = capabilities

        state.active_agents[agent_id] = agent_info
        state.increment_version(agent_id)
        return state

    return _locked_read_modify_write(state_path, _modify)
