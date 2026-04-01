"""Migration tools for importing existing knowledge into the Cognitive Ledger.

Converts three existing knowledge stores into CLP ledger entries:
1. MEMORY.md -- agent memory files with structured sections
2. Coordination bus -- TSV bus messages (DECISION, CORRECTION, MILESTONE)
3. Git log -- commit messages as discoveries

All imports are idempotent: re-running produces the same entries (deterministic
IDs based on content hash).
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hummbl_clp.core.ledger_writer import post_entry, read_entries
from hummbl_clp.core.models import (
    LedgerEntry,
    compute_content_hash,
)

logger = logging.getLogger(__name__)


def _deterministic_id(content: str, source: str) -> str:
    """Generate a deterministic CLP ID from content + source."""
    digest = hashlib.sha256(
        f"{source}:{content}".encode("utf-8")
    ).hexdigest()[:12]
    return f"clp-{digest}"


def _resolve_repo_root() -> Path | None:
    """Resolve git repo root."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return Path(root) if root else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# MEMORY.md Import
# ---------------------------------------------------------------------------

def _parse_memory_sections(text: str) -> list[dict[str, Any]]:
    """Parse a MEMORY.md file into sections with bullet content."""
    sections: list[dict[str, Any]] = []
    current_heading = ""
    current_bullets: list[str] = []

    for line in text.splitlines():
        heading_match = re.match(r"^##\s+(.+)$", line)
        if heading_match:
            if current_heading and current_bullets:
                sections.append({
                    "heading": current_heading,
                    "bullets": current_bullets,
                })
            current_heading = heading_match.group(1).strip()
            current_bullets = []
            continue

        stripped = line.rstrip()
        if stripped.startswith("- ") and not line.startswith("  "):
            current_bullets.append(stripped[2:].strip())

    if current_heading and current_bullets:
        sections.append({
            "heading": current_heading,
            "bullets": current_bullets,
        })

    return sections


def _section_to_scope(heading: str) -> str:
    """Map a MEMORY.md section heading to a CLP scope."""
    heading_lower = heading.lower()
    if "gotcha" in heading_lower or "constraint" in heading_lower:
        return "convention"
    if "architecture" in heading_lower or "setup" in heading_lower:
        return "project"
    if "sprint" in heading_lower or "session" in heading_lower:
        return "process"
    if "coordination" in heading_lower or "agent" in heading_lower:
        return "process"
    return "project"


def _section_to_type(heading: str) -> str:
    """Map a MEMORY.md section heading to a CLP entry type."""
    heading_lower = heading.lower()
    if "gotcha" in heading_lower:
        return "lesson"
    if "constraint" in heading_lower:
        return "convention"
    if "architecture" in heading_lower or "insight" in heading_lower:
        return "discovery"
    if "sprint" in heading_lower or "session" in heading_lower:
        return "discovery"
    if "decision" in heading_lower:
        return "decision"
    return "lesson"


def _section_to_tags(heading: str) -> tuple[str, ...]:
    """Extract tags from a MEMORY.md section heading."""
    tags = ["imported", "memory-md"]
    heading_lower = heading.lower()
    if "gotcha" in heading_lower:
        tags.append("gotcha")
    if "security" in heading_lower:
        tags.append("security")
    if "ci" in heading_lower or "workflow" in heading_lower:
        tags.append("ci")
    if "sprint" in heading_lower:
        tags.append("sprint")
    if "agent" in heading_lower or "coordination" in heading_lower:
        tags.append("coordination")
    return tuple(tags[:10])


def import_from_memory_md(
    memory_path: str | Path,
    *,
    ledger_path: str | Path | None = None,
    agent: str = "migration",
    vendor: str = "human",
    model: str = "manual",
    dry_run: bool = False,
) -> list[LedgerEntry]:
    """Import bullet points from a MEMORY.md file into the cognitive ledger."""
    path = Path(memory_path)
    if not path.exists():
        logger.warning("MEMORY.md not found: %s", path)
        return []

    text = path.read_text(encoding="utf-8")
    sections = _parse_memory_sections(text)

    existing_ids: set[str] = set()
    if not dry_run:
        existing = read_entries(ledger_path=ledger_path, limit=10000)
        existing_ids = {e.id for e in existing}

    entries: list[LedgerEntry] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for section in sections:
        heading = section["heading"]
        entry_type = _section_to_type(heading)
        scope = _section_to_scope(heading)
        tags = _section_to_tags(heading)

        for bullet in section["bullets"]:
            content = bullet[:4096] if len(bullet) > 4096 else bullet
            if not content.strip():
                continue

            entry_id = _deterministic_id(content, f"memory:{heading}")

            if entry_id in existing_ids:
                logger.debug("Skipping duplicate: %s", entry_id)
                continue

            content_hash = compute_content_hash(
                agent=agent,
                vendor=vendor,
                model=model,
                entry_type=entry_type,
                scope=scope,
                content=content,
            )

            entry = LedgerEntry(
                id=entry_id,
                timestamp=timestamp,
                agent=agent,
                vendor=vendor,
                model=model,
                type=entry_type,
                scope=scope,
                content=content,
                content_hash=content_hash,
                tags=tags,
                assurance_level="SELF",
            )

            if not dry_run:
                try:
                    post_entry(entry, ledger_path=ledger_path)
                except (ValueError, OSError) as e:
                    logger.warning("Failed to post entry %s: %s", entry_id, e)
                    continue

            entries.append(entry)

    logger.info(
        "Imported %d entries from MEMORY.md (%d sections)",
        len(entries),
        len(sections),
    )
    return entries


# ---------------------------------------------------------------------------
# Bus History Import
# ---------------------------------------------------------------------------

_BUS_TYPE_MAP: dict[str, str] = {
    "DECISION": "decision",
    "CORRECTION": "correction",
    "MILESTONE": "discovery",
    "COMPLETE": "discovery",
    "SESSION_COMPLETE": "discovery",
}


def import_from_bus_history(
    bus_path: str | Path | None = None,
    *,
    ledger_path: str | Path | None = None,
    since: str | None = None,
    msg_types: set[str] | None = None,
    dry_run: bool = False,
) -> list[LedgerEntry]:
    """Import relevant bus messages into the cognitive ledger."""
    if msg_types is None:
        msg_types = set(_BUS_TYPE_MAP.keys())

    if bus_path is None:
        root = _resolve_repo_root()
        if root:
            bus_path = root / "_state" / "coordination" / "messages.tsv"
        else:
            bus_path = Path("_state/coordination/messages.tsv")
    bus_path = Path(bus_path)

    if not bus_path.exists():
        logger.warning("Bus file not found: %s", bus_path)
        return []

    existing_ids: set[str] = set()
    if not dry_run:
        existing = read_entries(ledger_path=ledger_path, limit=10000)
        existing_ids = {e.id for e in existing}

    entries: list[LedgerEntry] = []

    with open(bus_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.rstrip("\n\r")
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) != 5:
                continue

            ts, sender, recipient, msg_type, message = parts

            if ts == "timestamp":
                continue
            if msg_type not in msg_types:
                continue
            if since and ts < since:
                continue

            entry_type = _BUS_TYPE_MAP.get(msg_type, "discovery")

            content = message.replace("\\n", "\n").strip()
            if not content:
                continue
            content = content[:4096]

            vendor = _sender_to_vendor(sender)
            entry_id = _deterministic_id(content, f"bus:{ts}:{sender}")

            if entry_id in existing_ids:
                continue

            content_hash = compute_content_hash(
                agent=sender,
                vendor=vendor,
                model="unknown",
                entry_type=entry_type,
                scope="project",
                content=content,
            )

            entry = LedgerEntry(
                id=entry_id,
                timestamp=ts,
                agent=sender,
                vendor=vendor,
                model="unknown",
                type=entry_type,
                scope="project",
                content=content,
                content_hash=content_hash,
                evidence=f"bus:line:{line_num}",
                tags=("imported", "bus-history", msg_type.lower()),
                assurance_level="SELF",
            )

            if not dry_run:
                try:
                    post_entry(entry, ledger_path=ledger_path)
                except (ValueError, OSError) as e:
                    logger.warning(
                        "Failed to post bus entry %s (line %d): %s",
                        entry_id, line_num, e,
                    )
                    continue

            entries.append(entry)

    logger.info("Imported %d entries from bus history", len(entries))
    return entries


def _sender_to_vendor(sender: str) -> str:
    """Map a bus sender identity to a vendor."""
    sender_lower = sender.lower()
    if "claude" in sender_lower:
        return "anthropic"
    if "codex" in sender_lower:
        return "openai"
    if "kimi" in sender_lower:
        return "moonshot"
    if "gemini" in sender_lower:
        return "google"
    return "local"


# ---------------------------------------------------------------------------
# Git Log Import
# ---------------------------------------------------------------------------

def import_from_git_log(
    *,
    ledger_path: str | Path | None = None,
    since: str | None = None,
    max_commits: int = 100,
    dry_run: bool = False,
) -> list[LedgerEntry]:
    """Import git commit messages as discovery entries."""
    cmd = [
        "git", "log",
        f"--max-count={max_commits}",
        "--format=%H%n%aI%n%an%n%s",
    ]
    if since:
        cmd.append(f"--since={since}")

    try:
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("Git log failed -- not in a git repo?")
        return []

    if not output.strip():
        return []

    existing_ids: set[str] = set()
    if not dry_run:
        existing = read_entries(ledger_path=ledger_path, limit=10000)
        existing_ids = {e.id for e in existing}

    entries: list[LedgerEntry] = []
    lines = output.strip().split("\n")

    i = 0
    while i + 3 < len(lines):
        commit_hash = lines[i].strip()
        commit_date = lines[i + 1].strip()
        author = lines[i + 2].strip()
        subject = lines[i + 3].strip()
        i += 4

        if not subject:
            continue

        try:
            dt = datetime.fromisoformat(commit_date)
            timestamp = dt.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except ValueError:
            timestamp = commit_date

        vendor = _author_to_vendor(author)
        content = f"{subject}"
        if len(content) > 4096:
            content = content[:4096]

        entry_id = _deterministic_id(content, f"git:{commit_hash[:12]}")

        if entry_id in existing_ids:
            continue

        entry_type = _commit_prefix_to_type(subject)

        content_hash = compute_content_hash(
            agent=f"git:{author}",
            vendor=vendor,
            model="git",
            entry_type=entry_type,
            scope="project",
            content=content,
        )

        entry = LedgerEntry(
            id=entry_id,
            timestamp=timestamp,
            agent=f"git:{author}",
            vendor=vendor,
            model="git",
            type=entry_type,
            scope="project",
            content=content,
            content_hash=content_hash,
            evidence=f"commit:{commit_hash[:12]}",
            tags=("imported", "git-log"),
            assurance_level="VERIFIED",
        )

        if not dry_run:
            try:
                post_entry(entry, ledger_path=ledger_path)
            except (ValueError, OSError) as e:
                logger.warning(
                    "Failed to post git entry %s: %s", entry_id, e,
                )
                continue

        entries.append(entry)

    logger.info("Imported %d entries from git log", len(entries))
    return entries


def _author_to_vendor(author: str) -> str:
    """Map a git author to a vendor."""
    author_lower = author.lower()
    if "claude" in author_lower or "anthropic" in author_lower:
        return "anthropic"
    if "codex" in author_lower or "openai" in author_lower:
        return "openai"
    if "kimi" in author_lower or "moonshot" in author_lower:
        return "moonshot"
    if "gemini" in author_lower or "google" in author_lower:
        return "google"
    return "human"


def _commit_prefix_to_type(subject: str) -> str:
    """Map a conventional commit prefix to a CLP entry type."""
    subject_lower = subject.lower()
    if subject_lower.startswith("fix"):
        return "correction"
    if subject_lower.startswith("feat"):
        return "discovery"
    if subject_lower.startswith("refactor"):
        return "decision"
    if subject_lower.startswith("docs"):
        return "convention"
    if subject_lower.startswith("chore"):
        return "convention"
    return "discovery"
