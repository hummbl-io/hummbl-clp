"""Cognitive Ledger writer -- append-only JSONL persistence with file locking.

Provides the canonical write path for the cognitive ledger. All ledger
writes should go through post_entry() to ensure mutual exclusion via
the platform-appropriate advisory lock backend.

Mirrors the design of bus/bus_writer.py for the coordination bus.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import unicodedata
from pathlib import Path

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None

try:
    import msvcrt  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised on POSIX
    msvcrt = None

from hummbl_clp.core.models import (
    LedgerEntry,
    LedgerEntryType,
    LedgerScope,
)

logger = logging.getLogger(__name__)

# Default ledger location (relative to repo root)
DEFAULT_LEDGER_PATH = "_state/cognition/ledger.jsonl"

# Maximum entry content size (4 KB -- matches schema maxLength)
MAX_CONTENT_BYTES = 4096
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

# ---------------------------------------------------------------------------
# Content scanning -- reject poisoned entries before they reach the ledger
# ---------------------------------------------------------------------------

# Prompt injection patterns (case-insensitive)
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?prior\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"system\s+prompt\s+override", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"\]\s*\}\s*\]\s*\}\s*system", re.IGNORECASE),  # JSON escape
]

# Credential patterns
_CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),          # OpenAI keys
    re.compile(r"sk-ant-[a-zA-Z0-9-]{20,}"),      # Anthropic keys
    re.compile(r"ghp_[a-zA-Z0-9]{36,}"),           # GitHub PATs
    re.compile(r"gho_[a-zA-Z0-9]{36,}"),           # GitHub OAuth
    re.compile(r"glpat-[a-zA-Z0-9_-]{20,}"),       # GitLab PATs
    re.compile(r"xoxb-[a-zA-Z0-9-]{20,}"),         # Slack bot tokens
    re.compile(r"xoxp-[a-zA-Z0-9-]{20,}"),         # Slack user tokens
    re.compile(r"AIza[a-zA-Z0-9_-]{35}"),           # Google API keys
    re.compile(r"AKIA[A-Z0-9]{16}"),                # AWS access keys
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),  # PEM keys
]

# Exfiltration vectors (commands that could leak secrets)
_EXFILTRATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"curl\s+.*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE),
    re.compile(r"wget\s+.*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE),
    re.compile(r"curl\s+-[^s]*d\s+.*\$\{?\w*", re.IGNORECASE),
]

# Invisible Unicode characters used for steganographic attacks.
# Covers: zero-width chars, bidi controls, format chars, unusual whitespace,
# variation selectors, and tag characters. Expanded after pre-mortem found
# U+1680 (Ogham Space) bypass.
_INVISIBLE_CODEPOINTS = frozenset({
    # Zero-width characters
    "\u200b",  # Zero-width space
    "\u200c",  # Zero-width non-joiner
    "\u200d",  # Zero-width joiner
    "\u2060",  # Word joiner
    "\ufeff",  # Zero-width no-break space (BOM)
    # Bidi controls
    "\u200e",  # Left-to-right mark
    "\u200f",  # Right-to-left mark
    "\u202a",  # Left-to-right embedding
    "\u202b",  # Right-to-left embedding
    "\u202c",  # Pop directional formatting
    "\u202d",  # Left-to-right override
    "\u202e",  # Right-to-left override
    "\u2066",  # Left-to-right isolate
    "\u2067",  # Right-to-left isolate
    "\u2068",  # First strong isolate
    "\u2069",  # Pop directional isolate
    # Unusual whitespace (pre-mortem finding: Ogham Space bypass)
    "\u00a0",  # Non-breaking space
    "\u1680",  # Ogham Space Mark
    "\u2000",  # En Quad
    "\u2001",  # Em Quad
    "\u2002",  # En Space
    "\u2003",  # Em Space
    "\u2004",  # Three-per-em space
    "\u2005",  # Four-per-em space
    "\u2006",  # Six-per-em space
    "\u2007",  # Figure space
    "\u2008",  # Punctuation space
    "\u2009",  # Thin space
    "\u200a",  # Hair space
    "\u205f",  # Medium mathematical space
    "\u3000",  # Ideographic space
    # Format characters
    "\u00ad",  # Soft hyphen
    "\u034f",  # Combining grapheme joiner
    "\u061c",  # Arabic letter mark
    "\u180e",  # Mongolian vowel separator
    # Variation selectors (can alter glyph rendering)
    "\ufe00",  # Variation Selector-1
    "\ufe0f",  # Variation Selector-16 (emoji presentation)
    # Interlinear annotation anchors
    "\ufff9",  # Interlinear annotation anchor
    "\ufffa",  # Interlinear annotation separator
    "\ufffb",  # Interlinear annotation terminator
})


class ContentScanError(ValueError):
    """Raised when content scanning detects a suspicious pattern."""

    def __init__(self, category: str, detail: str) -> None:
        self.category = category
        self.detail = detail
        super().__init__(f"Content scan rejected ({category}): {detail}")


def scan_content(text: str) -> None:
    """Scan text for prompt injection, credentials, exfiltration, and invisible chars.

    Text is NFC-normalized before regex matching to prevent homographic
    bypass attacks (e.g., Cyrillic 'а' vs Latin 'a'). Invisible character
    detection runs on the RAW text (pre-normalization) to catch chars that
    NFC would strip.

    Raises ContentScanError if suspicious content is detected.
    Scans all text fields that flow into the ledger and ultimately into
    boot context for other agents.
    """
    # 0. Check invisible chars on RAW text (before normalization strips them)
    found_invisible = [c for c in text if c in _INVISIBLE_CODEPOINTS]
    if found_invisible:
        codepoints = ", ".join(f"U+{ord(c):04X}" for c in set(found_invisible))
        raise ContentScanError(
            "invisible_unicode",
            f"Contains invisible Unicode characters: {codepoints}",
        )

    # Normalize to NFC to prevent homographic bypass (Cyrillic 'а' vs Latin 'a')
    normalized = unicodedata.normalize("NFC", text)

    # 1. Prompt injection (on normalized text)
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            raise ContentScanError(
                "prompt_injection",
                f"Matches injection pattern: {match.group()!r}",
            )

    # 2. Credential leakage (on normalized text)
    for pattern in _CREDENTIAL_PATTERNS:
        match = pattern.search(normalized)
        if match:
            # Show first 8 chars only to avoid logging the full secret
            snippet = match.group()[:8] + "..."
            raise ContentScanError(
                "credential_leak",
                f"Contains credential-like pattern: {snippet}",
            )

    # 3. Exfiltration vectors (on normalized text)
    for pattern in _EXFILTRATION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            raise ContentScanError(
                "exfiltration",
                f"Contains exfiltration vector: {match.group()[:40]!r}",
            )


def _resolve_ledger_path(override: str | Path | None = None) -> Path:
    """Resolve the ledger file path.

    Priority: explicit override > COGNITION_LEDGER env > git root default.
    """
    if override:
        return Path(override)

    env_path = os.environ.get("COGNITION_LEDGER")
    if env_path:
        return Path(env_path)

    # Try git root
    try:
        import subprocess

        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if root:
            return Path(root) / DEFAULT_LEDGER_PATH
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return Path(DEFAULT_LEDGER_PATH)


def _resolve_signing_secret() -> bytes | None:
    """Resolve HMAC signing secret from BUS_SIGNING_SECRET env var."""
    raw = os.environ.get("BUS_SIGNING_SECRET")
    if not raw:
        return None
    secret_bytes = raw.encode("utf-8")
    if len(secret_bytes) < 32:
        logger.warning(
            "BUS_SIGNING_SECRET too short (%d bytes, need 32+). "
            "Entries will NOT be signed.",
            len(secret_bytes),
        )
        return None
    return secret_bytes


def _sign_entry(entry_jsonl: str, secret: bytes) -> str:
    """Compute HMAC-SHA256 signature of a JSONL line."""
    return hmac.new(
        secret, entry_jsonl.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _harden_file_permissions(path: Path) -> None:
    """Set restrictive permissions (0o600) on the ledger file."""
    if not path.exists():
        return
    try:
        current_mode = path.stat().st_mode & 0o777
        if current_mode != 0o660:
            path.chmod(0o660)
    except OSError as e:
        logger.warning("Could not harden ledger permissions: %s", e)


def post_entry(
    entry: LedgerEntry,
    *,
    ledger_path: str | Path | None = None,
    secret: bytes | None = None,
) -> LedgerEntry:
    """Append a ledger entry to the JSONL file under exclusive lock.

    Parameters
    ----------
    entry : LedgerEntry
        The entry to write. Must have a valid content_hash.
    ledger_path : str | Path | None
        Override ledger file path. Defaults to auto-resolve.
    secret : bytes | None
        HMAC-SHA256 key for signing. Falls back to BUS_SIGNING_SECRET env.

    Returns:
    -------
    LedgerEntry
        The entry as written (may include signature if signing enabled).

    Raises:
    ------
    ValueError
        If entry fails validation.
    OSError
        If file write fails.
    """
    path = _resolve_ledger_path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Scan content for injection, credentials, exfiltration, invisible chars.
    # This runs BEFORE hash verification to reject poisoned content early.
    scan_content(entry.content)
    if entry.evidence:
        scan_content(entry.evidence)
    if entry.tags:
        scan_content(" ".join(entry.tags))
    if entry.agent:
        scan_content(entry.agent)

    # Verify content hash
    if not entry.verify_hash():
        raise ValueError(
            "Content hash mismatch: entry content_hash does not match "
            "computed hash of content fields"
        )

    # Resolve signing secret
    if secret is None:
        secret = _resolve_signing_secret()

    # Sign if secret available
    if secret is not None and entry.signature is None:
        jsonl_line = entry.to_jsonl()
        sig = _sign_entry(jsonl_line, secret)
        # Reconstruct entry with signature
        d = entry.to_dict()
        d["signature"] = sig
        entry = LedgerEntry.from_dict(d)

    line = entry.to_jsonl() + "\n"

    # Append under exclusive advisory lock
    with open(path, "a", encoding="utf-8") as f:
        _lock_file(f)
        try:
            # Check if we just created the file (size 0 before our write)
            is_new_file = f.tell() == 0
            f.write(line)
            f.flush()
        finally:
            _unlock_file(f)

    # Harden permissions on new files
    if is_new_file:
        _harden_file_permissions(path)

    logger.info(
        "Ledger entry posted: id=%s type=%s scope=%s agent=%s",
        entry.id,
        entry.type,
        entry.scope,
        entry.agent,
    )

    return entry


def read_entries(
    *,
    ledger_path: str | Path | None = None,
    since: str | None = None,
    entry_type: str | LedgerEntryType | None = None,
    scope: str | LedgerScope | None = None,
    agent: str | None = None,
    tags: list[str] | None = None,
    limit: int = 100,
) -> list[LedgerEntry]:
    """Read and filter ledger entries.

    Parameters
    ----------
    ledger_path : str | Path | None
        Override ledger file path.
    since : str | None
        ISO 8601 timestamp -- only return entries after this time.
    entry_type : str | LedgerEntryType | None
        Filter by entry type.
    scope : str | LedgerScope | None
        Filter by scope.
    agent : str | None
        Filter by agent identifier (substring match).
    tags : list[str] | None
        Filter by tags (entries must contain ALL specified tags).
    limit : int
        Maximum number of entries to return (most recent first).

    Returns:
    -------
    list[LedgerEntry]
        Matching entries, most recent first.
    """
    path = _resolve_ledger_path(ledger_path)
    if not path.exists():
        return []

    # Normalize filter values
    if isinstance(entry_type, LedgerEntryType):
        entry_type = entry_type.value
    if isinstance(scope, LedgerScope):
        scope = scope.value

    entries: list[LedgerEntry] = []

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entry = LedgerEntry.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("Skipping malformed ledger line %d: %s", line_num, e)
                continue

            # Apply filters
            if since and entry.timestamp < since:
                continue
            if entry_type and entry.type != entry_type:
                continue
            if scope and entry.scope != scope:
                continue
            if agent and agent not in entry.agent:
                continue
            if tags and not all(t in entry.tags for t in tags):
                continue

            entries.append(entry)

    # Most recent first, limited
    entries.reverse()
    return entries[:limit]


def validate_integrity(
    *,
    ledger_path: str | Path | None = None,
    secret: bytes | None = None,
) -> tuple[int, list[str]]:
    """Validate ledger integrity: parsing, content hashes, optional signatures.

    Returns:
    -------
    tuple[int, list[str]]
        (valid_count, error_descriptions)
    """
    path = _resolve_ledger_path(ledger_path)
    if not path.exists():
        return 0, []

    if secret is None:
        secret = _resolve_signing_secret()

    valid_count = 0
    errors: list[str] = []

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            # Parse
            try:
                data = json.loads(line)
                entry = LedgerEntry.from_dict(data)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                errors.append(f"Line {line_num}: parse error: {e}")
                continue

            # Verify content hash
            if not entry.verify_hash():
                errors.append(
                    f"Line {line_num}: content_hash mismatch for {entry.id}"
                )
                continue

            # Verify signature if present and secret available
            if entry.signature and secret:
                # Reconstruct unsigned JSONL to verify
                d = entry.to_dict()
                d.pop("signature", None)
                unsigned_entry = LedgerEntry.from_dict({**d, "signature": None})
                unsigned_jsonl = unsigned_entry.to_jsonl()
                expected_sig = _sign_entry(unsigned_jsonl, secret)
                if not hmac.compare_digest(entry.signature, expected_sig):
                    errors.append(
                        f"Line {line_num}: signature mismatch for {entry.id}"
                    )
                    continue

            valid_count += 1

    return valid_count, errors
