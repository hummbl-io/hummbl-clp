"""Data models for the Cognitive Ledger Protocol.

Defines LedgerEntry (append-only shared memory) and SharedState (mutable snapshot).
All models use stdlib dataclasses only -- zero third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class LedgerEntryType(str, Enum):
    """Type of knowledge being recorded."""

    LESSON = "lesson"  # Earned understanding from experience
    DECISION = "decision"  # Architectural or process decision with reasoning
    DISCOVERY = "discovery"  # New finding about the codebase or domain
    CORRECTION = "correction"  # Fixes a previous entry (uses supersedes)
    CONVENTION = "convention"  # Established pattern or rule


class LedgerScope(str, Enum):
    """Scope of the knowledge entry."""

    PROJECT = "project"  # Project-wide knowledge
    MODULE = "module"  # Specific module or package
    FILE = "file"  # Specific file
    CONVENTION = "convention"  # Coding/process convention
    PROCESS = "process"  # Operational process


class AssuranceLevel(str, Enum):
    """Trust level of the entry."""

    SELF = "SELF"  # Agent asserts its own learning
    PEER = "PEER"  # Another agent reviewed and confirmed
    VERIFIED = "VERIFIED"  # Human or governance process verified


# Allowed vendor identifiers
VALID_VENDORS = frozenset({
    "anthropic", "openai", "google", "moonshot", "local", "human",
})


def _generate_entry_id() -> str:
    """Generate a CLP entry ID: clp-<12 hex chars>."""
    return f"clp-{uuid.uuid4().hex[:12]}"


def _utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_content_hash(
    *,
    agent: str,
    vendor: str,
    model: str,
    entry_type: str,
    scope: str,
    content: str,
) -> str:
    """Compute SHA-256 hash of canonical entry content.

    The hash covers the immutable semantic fields (not id, timestamp,
    signature, or metadata like tags/confidence). This allows tamper
    detection without requiring HMAC keys.
    """
    canonical = json.dumps(
        {
            "agent": agent,
            "content": content,
            "model": model,
            "scope": scope,
            "type": entry_type,
            "vendor": vendor,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    """Single entry in the cognitive ledger (append-only shared memory).

    Each entry represents a piece of earned understanding -- a lesson learned,
    a decision made, a discovery, or a correction to prior knowledge.
    """

    # Identity
    id: str  # clp-<12 hex chars>
    timestamp: str  # ISO 8601 UTC with Z suffix

    # Provenance
    agent: str  # Agent identifier (e.g., "claude-code (god-mode)")
    vendor: str  # Vendor identifier (anthropic, openai, google, etc.)
    model: str  # Model identifier (e.g., "claude-opus-4-6")

    # Content
    type: str  # LedgerEntryType value
    scope: str  # LedgerScope value
    content: str  # The actual knowledge (max 4096 chars)

    # Integrity
    content_hash: str  # SHA-256 hex of canonical content fields

    # Optional metadata
    evidence: str | None = None  # Link to supporting artifact
    confidence: float = 0.9  # 0.0 to 1.0
    supersedes: str | None = None  # ID of entry this corrects
    tags: tuple[str, ...] = ()  # Categorization tags (max 10)
    assurance_level: str | None = None  # SELF, PEER, or VERIFIED
    signature: str | None = None  # HMAC-SHA256 hex (optional)
    links: tuple[str, ...] = ()  # Related entry IDs (max 20, Zettelkasten-style)

    def __post_init__(self) -> None:
        """Validate entry fields."""
        if not self.id.startswith("clp-") or len(self.id) != 16:
            raise ValueError(
                f"Invalid entry ID format: {self.id!r} "
                "(expected clp-<12 hex chars>)"
            )
        if self.vendor not in VALID_VENDORS:
            raise ValueError(
                f"Invalid vendor: {self.vendor!r} "
                f"(expected one of {sorted(VALID_VENDORS)})"
            )
        if self.type not in {e.value for e in LedgerEntryType}:
            raise ValueError(
                f"Invalid type: {self.type!r} "
                f"(expected one of {[e.value for e in LedgerEntryType]})"
            )
        if self.scope not in {e.value for e in LedgerScope}:
            raise ValueError(
                f"Invalid scope: {self.scope!r} "
                f"(expected one of {[e.value for e in LedgerScope]})"
            )
        if not self.content or len(self.content) > 4096:
            raise ValueError(
                f"Content must be 1-4096 chars, got {len(self.content)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be 0.0-1.0, got {self.confidence}"
            )
        if len(self.tags) > 10:
            raise ValueError(f"Maximum 10 tags, got {len(self.tags)}")
        if self.assurance_level is not None:
            if self.assurance_level not in {e.value for e in AssuranceLevel}:
                raise ValueError(
                    f"Invalid assurance_level: {self.assurance_level!r}"
                )
        if self.supersedes is not None and not self.supersedes.startswith("clp-"):
            raise ValueError(
                f"supersedes must be a valid CLP ID: {self.supersedes!r}"
            )
        if len(self.links) > 20:
            raise ValueError(f"Maximum 20 links, got {len(self.links)}")
        for link_id in self.links:
            if not link_id.startswith("clp-") or len(link_id) != 16:
                raise ValueError(
                    f"Invalid link ID format: {link_id!r} "
                    "(expected clp-<12 hex chars>)"
                )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        d: dict[str, Any] = {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "vendor": self.vendor,
            "model": self.model,
            "type": self.type,
            "scope": self.scope,
            "content": self.content,
            "content_hash": self.content_hash,
        }
        if self.evidence is not None:
            d["evidence"] = self.evidence
        d["confidence"] = self.confidence
        if self.supersedes is not None:
            d["supersedes"] = self.supersedes
        if self.tags:
            d["tags"] = list(self.tags)
        if self.assurance_level is not None:
            d["assurance_level"] = self.assurance_level
        if self.signature is not None:
            d["signature"] = self.signature
        if self.links:
            d["links"] = list(self.links)
        return d

    def to_jsonl(self) -> str:
        """Serialize to compact JSON line."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEntry:
        """Deserialize from dictionary."""
        tags = data.get("tags", [])
        if isinstance(tags, list):
            tags = tuple(tags)
        links = data.get("links", [])
        if isinstance(links, list):
            links = tuple(links)
        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            agent=data["agent"],
            vendor=data["vendor"],
            model=data["model"],
            type=data["type"],
            scope=data["scope"],
            content=data["content"],
            content_hash=data["content_hash"],
            evidence=data.get("evidence"),
            confidence=data.get("confidence", 0.9),
            supersedes=data.get("supersedes"),
            tags=tags,
            assurance_level=data.get("assurance_level"),
            signature=data.get("signature"),
            links=links,
        )

    def verify_hash(self) -> bool:
        """Verify that content_hash matches the canonical content fields."""
        expected = compute_content_hash(
            agent=self.agent,
            vendor=self.vendor,
            model=self.model,
            entry_type=self.type,
            scope=self.scope,
            content=self.content,
        )
        return self.content_hash == expected

    @classmethod
    def create(
        cls,
        *,
        agent: str,
        vendor: str,
        model: str,
        entry_type: str | LedgerEntryType,
        scope: str | LedgerScope,
        content: str,
        evidence: str | None = None,
        confidence: float = 0.9,
        supersedes: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
        assurance_level: str | None = None,
        links: tuple[str, ...] | list[str] = (),
    ) -> LedgerEntry:
        """Factory method to create a new ledger entry with auto-generated ID,
        timestamp, and content hash.
        """
        if isinstance(entry_type, LedgerEntryType):
            entry_type = entry_type.value
        if isinstance(scope, LedgerScope):
            scope = scope.value
        if isinstance(tags, list):
            tags = tuple(tags)
        if isinstance(links, list):
            links = tuple(links)

        entry_id = _generate_entry_id()
        timestamp = _utc_now_iso()
        content_hash = compute_content_hash(
            agent=agent,
            vendor=vendor,
            model=model,
            entry_type=entry_type,
            scope=scope,
            content=content,
        )
        return cls(
            id=entry_id,
            timestamp=timestamp,
            agent=agent,
            vendor=vendor,
            model=model,
            type=entry_type,
            scope=scope,
            content=content,
            content_hash=content_hash,
            evidence=evidence,
            confidence=confidence,
            supersedes=supersedes,
            tags=tags,
            assurance_level=assurance_level,
            links=links,
        )


@dataclass
class SharedState:
    """Mutable snapshot of multi-agent coordination state (Layer 1).

    Unlike the append-only ledger, this file is overwritten atomically.
    Uses optimistic concurrency via the version field.
    """

    version: int = 0
    updated_at: str = ""
    updated_by: str = ""
    active_agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    claimed_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_decisions: list[dict[str, Any]] = field(default_factory=list)
    sprint: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)

    def increment_version(self, updated_by: str) -> None:
        """Bump version and update metadata."""
        self.version += 1
        self.updated_at = _utc_now_iso()
        self.updated_by = updated_by

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "active_agents": self.active_agents,
            "claimed_files": self.claimed_files,
            "active_decisions": self.active_decisions,
            "sprint": self.sprint,
            "flags": self.flags,
        }

    def to_json(self) -> str:
        """Serialize to pretty JSON."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SharedState:
        """Deserialize from dictionary."""
        return cls(
            version=data.get("version", 0),
            updated_at=data.get("updated_at", ""),
            updated_by=data.get("updated_by", ""),
            active_agents=data.get("active_agents", {}),
            claimed_files=data.get("claimed_files", {}),
            active_decisions=data.get("active_decisions", []),
            sprint=data.get("sprint", {}),
            flags=data.get("flags", {}),
        )

    @classmethod
    def from_json(cls, text: str) -> SharedState:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(text))
