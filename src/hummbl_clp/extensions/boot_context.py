"""Agent boot context builder.

Reads all three layers of the Cognitive Ledger and produces a single
markdown string suitable for injecting into an agent's system prompt
or session start hook.

FROZEN SNAPSHOT CONTRACT:
    Boot context is computed ONCE at session start and is immutable for
    the lifetime of that session.  Ledger writes that occur mid-session
    are persisted to disk immediately but are NOT reflected in the
    running session's boot context.  The next session will see them.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from hummbl_clp.core.models import SharedState
from hummbl_clp.core.query import summarize_for_boot

logger = logging.getLogger(__name__)

# Type priority for boot context (lower = more important)
_TYPE_PRIORITY = {
    "decision": 0,
    "correction": 1,
    "lesson": 2,
    "convention": 3,
    "discovery": 4,
}


def _summarize_indexed(
    cog_dir: Path,
    max_entries: int,
    max_age_days: int,
) -> str | None:
    """Try to produce boot summary from BM25 index metadata."""
    from datetime import datetime, timedelta, timezone

    index_path = cog_dir / "index.json"
    if not index_path.exists():
        return None

    try:
        from hummbl_clp.core.indexer import BM25Index

        index = BM25Index()
        if not index.load(path=index_path):
            return None

        if not index.doc_meta:
            return None

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        candidates = []
        for doc_id, meta in index.doc_meta.items():
            ts = meta.get("timestamp", "")
            if ts < cutoff:
                continue
            entry_type = meta.get("type", "")
            priority = _TYPE_PRIORITY.get(entry_type, 5)
            candidates.append((priority, ts, doc_id, meta))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1]))
        candidates = candidates[:max_entries]

        lines: list[str] = []
        for _, ts, _, meta in candidates:
            prefix = meta.get("type", "?").upper()
            agent = meta.get("agent", "?")
            content = meta.get("content_preview", "")[:200]
            tags = meta.get("tags", [])
            tags_str = f" [{', '.join(tags)}]" if tags else ""
            lines.append(
                f"- [{ts[:10]}] ({agent}) {prefix}: {content}{tags_str}"
            )

        return "\n".join(lines) if lines else None

    except (OSError, ValueError, KeyError) as e:
        logger.debug("Index-based boot context failed: %s", e)
        return None


# Default cognition directory
DEFAULT_COGNITION_DIR = "_state/cognition"


def _resolve_cognition_dir(override: str | Path | None = None) -> Path:
    """Resolve the cognition directory path."""
    if override:
        return Path(override)
    env_path = os.environ.get("COGNITION_DIR")
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
            return Path(root) / DEFAULT_COGNITION_DIR
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path(DEFAULT_COGNITION_DIR)


def build_boot_context(
    cognition_dir: str | Path | None = None,
    *,
    max_entries: int = 20,
    max_age_days: int = 14,
) -> str:
    """Build a complete boot context from all three cognitive layers.

    Parameters
    ----------
    cognition_dir : str | Path | None
        Path to the cognition directory containing state.json,
        ledger.jsonl, and intent.md.
    max_entries : int
        Maximum ledger entries to include.
    max_age_days : int
        Only include entries from the last N days.

    Returns
    -------
    str
        Markdown-formatted boot context ready for agent injection.
    """
    cog_dir = _resolve_cognition_dir(cognition_dir)
    parts: list[str] = ["# Cognitive Ledger Boot Context\n"]

    # --- Layer 3: Intent ---
    intent_path = cog_dir / "intent.md"
    if intent_path.exists():
        try:
            intent_text = intent_path.read_text(encoding="utf-8").strip()
            if intent_text:
                parts.append("## Current Intent\n")
                parts.append(intent_text)
                parts.append("")
        except OSError as e:
            logger.warning("Failed to read intent.md: %s", e)

    # --- Layer 1: State ---
    state_path = cog_dir / "state.json"
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            state = SharedState.from_dict(data)
            state_lines: list[str] = ["## Shared State\n"]

            if state.sprint:
                name = state.sprint.get("name", "unnamed")
                state_lines.append(f"- Sprint: {name}")

            if state.active_agents:
                agents = []
                for aid, info in sorted(state.active_agents.items()):
                    status = info.get("status", "?")
                    agents.append(f"{aid} ({status})")
                state_lines.append(f"- Agents: {', '.join(agents)}")

            if state.claimed_files:
                for fp, info in state.claimed_files.items():
                    agent = info.get("agent", "?")
                    purpose = info.get("purpose", "")
                    suffix = f" -- {purpose}" if purpose else ""
                    state_lines.append(f"- Claimed: {fp} ({agent}){suffix}")

            if state.flags:
                flags_str = ", ".join(
                    f"{k}={v}" for k, v in sorted(state.flags.items())
                )
                state_lines.append(f"- Flags: {flags_str}")

            if len(state_lines) > 1:
                parts.extend(state_lines)
                parts.append("")
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
            logger.warning("Failed to read state.json: %s", e)

    # --- Layer 2: Shared Memory ---
    ledger_path = cog_dir / "ledger.jsonl"
    if ledger_path.exists():
        summary = _summarize_indexed(cog_dir, max_entries, max_age_days)
        if not summary:
            summary = summarize_for_boot(
                ledger_path=ledger_path,
                max_entries=max_entries,
                max_age_days=max_age_days,
            )
        if summary and summary != "No recent learnings.":
            parts.append("## Recent Learnings\n")
            parts.append(summary)
            parts.append("")

    if len(parts) <= 1:
        parts.append("No cognitive data available yet.\n")

    return "\n".join(parts)
