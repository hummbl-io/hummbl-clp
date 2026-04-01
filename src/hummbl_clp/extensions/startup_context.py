"""Agent startup context builder.

Combines durable cognition state with recent coordination inbox messages so
agents can bootstrap from one canonical startup surface.
"""

from __future__ import annotations

import os
from pathlib import Path

from hummbl_clp.extensions.boot_context import build_boot_context

DEFAULT_BUS_PATH = "_state/coordination/messages.tsv"
DEFAULT_STARTUP_DIR = "_state/cognition/startup"


def _resolve_bus_path(override: str | Path | None = None) -> Path:
    """Resolve the coordination bus path."""
    if override:
        return Path(override)

    env_path = os.environ.get("COORDINATION_BUS_PATH")
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
            return Path(root) / DEFAULT_BUS_PATH
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return Path(DEFAULT_BUS_PATH)


def _resolve_startup_output_path(
    agent_id: str,
    override: str | Path | None = None,
) -> Path:
    """Resolve the startup context artifact path."""
    if override:
        return Path(override)

    safe_agent = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in agent_id
    ).strip("_") or "agent"

    try:
        import subprocess

        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if root:
            return Path(root) / DEFAULT_STARTUP_DIR / f"{safe_agent}.md"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return Path(DEFAULT_STARTUP_DIR) / f"{safe_agent}.md"


def _target_matches(target: str, tokens: list[str]) -> bool:
    """Return True when a bus target is addressed to the current agent."""
    lowered = target.strip().lower()
    if lowered == "all":
        return True
    return any(token in lowered for token in tokens)


def _unwrap_signing_envelope(message: str) -> str:
    """Strip signing envelope if present.

    This is a stub for the bus signing envelope unwrapper.
    In founder-mode this imports from founder_mode.bus.message_signing.
    Override or extend if your bus uses signed envelopes.
    """
    # TODO: integrate with hummbl-bus if signing envelopes are used
    return message


def read_recent_bus_inbox(
    agent_id: str,
    *,
    agent_aliases: list[str] | None = None,
    bus_path: str | Path | None = None,
    limit: int = 5,
) -> list[str]:
    """Return recent coordination rows addressed to this agent."""
    path = _resolve_bus_path(bus_path)
    if not path.exists():
        return []

    tokens = [agent_id.strip().lower()]
    if agent_aliases:
        tokens.extend(alias.strip().lower() for alias in agent_aliases if alias.strip())

    matches: list[str] = []
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            parts = raw_line.split("\t", 4)
            if len(parts) != 5:
                continue

            timestamp, sender, target, msg_type, message = parts
            if not _target_matches(target, tokens):
                continue

            message = _unwrap_signing_envelope(message)

            matches.append(
                f"- [{timestamp[:16]}] {sender} -> {target} ({msg_type}): "
                f"{message[:200]}"
            )
    except OSError:
        return []

    if limit <= 0:
        return []
    return matches[-limit:]


def build_startup_context(
    agent_id: str,
    *,
    agent_aliases: list[str] | None = None,
    cognition_dir: str | Path | None = None,
    bus_path: str | Path | None = None,
    max_entries: int = 20,
    max_age_days: int = 14,
    max_bus_messages: int = 5,
) -> str:
    """Build startup context for an agent from durable and transient memory."""
    parts = [
        build_boot_context(
            cognition_dir=cognition_dir,
            max_entries=max_entries,
            max_age_days=max_age_days,
        ).strip()
    ]

    inbox = read_recent_bus_inbox(
        agent_id,
        agent_aliases=agent_aliases,
        bus_path=bus_path,
        limit=max_bus_messages,
    )
    if inbox:
        parts.append("## Recent Bus Inbox\n")
        parts.extend(inbox)

    return "\n\n".join(part for part in parts if part).strip() + "\n"


def write_startup_context(
    agent_id: str,
    *,
    agent_aliases: list[str] | None = None,
    cognition_dir: str | Path | None = None,
    bus_path: str | Path | None = None,
    output_path: str | Path | None = None,
    max_entries: int = 20,
    max_age_days: int = 14,
    max_bus_messages: int = 5,
) -> Path:
    """Write startup context to a file and return the resolved path."""
    content = build_startup_context(
        agent_id,
        agent_aliases=agent_aliases,
        cognition_dir=cognition_dir,
        bus_path=bus_path,
        max_entries=max_entries,
        max_age_days=max_age_days,
        max_bus_messages=max_bus_messages,
    )

    path = _resolve_startup_output_path(agent_id, output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, path)
    return path
