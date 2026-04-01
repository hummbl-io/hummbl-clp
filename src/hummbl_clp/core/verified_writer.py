"""Helpers for writing durable, evidence-backed cognition entries."""

from __future__ import annotations

import os
from pathlib import Path

from hummbl_clp.core.ledger_writer import post_entry
from hummbl_clp.core.models import LedgerEntry, LedgerEntryType, LedgerScope

AGENT_ENV_VARS = ("COGNITION_AGENT", "FOUNDER_MODE_AGENT_ID", "AGENT_ID")
VENDOR_ENV_VARS = ("COGNITION_VENDOR",)
MODEL_ENV_VARS = ("COGNITION_MODEL",)


def _resolve_env_value(keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty environment value for the given keys."""
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


def resolve_entry_identity(
    *,
    agent: str | None = None,
    vendor: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str]:
    """Resolve entry identity from explicit args or environment."""
    resolved_agent = agent or _resolve_env_value(AGENT_ENV_VARS)
    resolved_vendor = vendor or _resolve_env_value(VENDOR_ENV_VARS)
    resolved_model = model or _resolve_env_value(MODEL_ENV_VARS)

    missing: list[str] = []
    if not resolved_agent:
        missing.append("agent")
    if not resolved_vendor:
        missing.append("vendor")
    if not resolved_model:
        missing.append("model")
    if missing:
        raise ValueError(
            "Missing required identity fields: "
            + ", ".join(missing)
            + ". Provide flags or set COGNITION_AGENT / COGNITION_VENDOR / "
            "COGNITION_MODEL."
        )

    return resolved_agent, resolved_vendor, resolved_model


def create_verified_entry(
    *,
    agent: str | None = None,
    vendor: str | None = None,
    model: str | None = None,
    entry_type: str | LedgerEntryType,
    scope: str | LedgerScope,
    content: str,
    evidence: str,
    confidence: float,
    supersedes: str | None = None,
    tags: tuple[str, ...] | list[str] = (),
    assurance_level: str | None = None,
) -> LedgerEntry:
    """Create a verified cognition entry with required evidence and confidence."""
    if not evidence or not evidence.strip():
        raise ValueError("Verified entries require non-empty evidence.")

    resolved_agent, resolved_vendor, resolved_model = resolve_entry_identity(
        agent=agent,
        vendor=vendor,
        model=model,
    )
    return LedgerEntry.create(
        agent=resolved_agent,
        vendor=resolved_vendor,
        model=resolved_model,
        entry_type=entry_type,
        scope=scope,
        content=content,
        evidence=evidence,
        confidence=confidence,
        supersedes=supersedes,
        tags=tags,
        assurance_level=assurance_level,
    )


def post_verified_entry(
    *,
    agent: str | None = None,
    vendor: str | None = None,
    model: str | None = None,
    entry_type: str | LedgerEntryType,
    scope: str | LedgerScope,
    content: str,
    evidence: str,
    confidence: float,
    supersedes: str | None = None,
    tags: tuple[str, ...] | list[str] = (),
    assurance_level: str | None = None,
    ledger_path: str | Path | None = None,
) -> LedgerEntry:
    """Create and persist a verified cognition entry."""
    entry = create_verified_entry(
        agent=agent,
        vendor=vendor,
        model=model,
        entry_type=entry_type,
        scope=scope,
        content=content,
        evidence=evidence,
        confidence=confidence,
        supersedes=supersedes,
        tags=tags,
        assurance_level=assurance_level,
    )
    return post_entry(entry, ledger_path=ledger_path)
