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
# U+1680 (Ogham Space) bypass; expanded again after the tag-character and
# variation-selector range gaps were verified (U+E0000-E007F accepted).
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
    "\u070f",  # Syriac abbreviation mark (invisible; overlines following text)
    "\u180e",  # Mongolian vowel separator
    # Invisible/deprecated format controls (same Cf neighborhood as the
    # listed U+2060 word joiner and U+2066-U+2069 isolates; a non-covered
    # format char could act as an invisible token separator)
    "\u2061",  # Function application (invisible)
    "\u2062",  # Invisible times
    "\u2063",  # Invisible separator
    "\u2064",  # Invisible plus
    "\u206a",  # Deprecated: inhibit symmetric swapping
    "\u206b",  # Deprecated: activate symmetric swapping
    "\u206c",  # Deprecated: inhibit Arabic form shaping
    "\u206d",  # Deprecated: activate Arabic form shaping
    "\u206e",  # Deprecated: national digit shapes
    "\u206f",  # Deprecated: nominal digit shapes
    # Interlinear annotation anchors
    "\ufff9",  # Interlinear annotation anchor
    "\ufffa",  # Interlinear annotation separator
    "\ufffb",  # Interlinear annotation terminator
})

# Invisible/format codepoint RANGES (checked as ranges, not set entries --
# 128+ tag chars and 240 variation selectors are impractical to enumerate).
#   U+FE00-U+FE0F   Variation Selectors 1-16 (alter glyph presentation)
#   U+E0000-U+E007F Tag characters: the classic ASCII-smuggling vector
#                   (U+E0020-E007E map 1:1 onto printable ASCII)
#   U+E0100-U+E01EF Variation Selectors Supplement
#   U+13430-U+1343F Egyptian hieroglyph format controls (invisible joiners)
#   U+1BCA0-U+1BCA3 Shorthand format controls (invisible letter overlaps)
#   U+1D173-U+1D17A Musical format controls (invisible begin/end marks)
_INVISIBLE_RANGES: tuple[tuple[int, int], ...] = (
    (0xFE00, 0xFE0F),
    (0x13430, 0x1343F),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE007F),
    (0xE0100, 0xE01EF),
)


def _is_invisible_char(c: str) -> bool:
    """Return True for any listed invisible singleton or ranged block."""
    if c in _INVISIBLE_CODEPOINTS:
        return True
    cp = ord(c)
    return any(lo <= cp <= hi for lo, hi in _INVISIBLE_RANGES)


# Script blocks whose codepoints include Latin lookalikes (confusables) --
# the homoglyph-injection signature is a token containing BOTH an ASCII
# Latin letter and one of these codepoints. Coverage is Cyrillic (all
# blocks) and Greek (basic + extended); other confusable scripts
# (fullwidth forms, Cherokee, Armenian, etc.) are NOT covered.
_CONFUSABLE_SCRIPT_RANGES: tuple[tuple[int, int], ...] = (
    (0x0370, 0x03FF),  # Greek and Coptic
    (0x1F00, 0x1FFF),  # Greek Extended
    (0x0400, 0x04FF),  # Cyrillic
    (0x0500, 0x052F),  # Cyrillic Supplement
    (0x2DE0, 0x2DFF),  # Cyrillic Extended-A
    (0xA640, 0xA69F),  # Cyrillic Extended-B
    (0x1C80, 0x1C8F),  # Cyrillic Extended-C
)


def _is_ascii_latin(c: str) -> bool:
    return "a" <= c <= "z" or "A" <= c <= "Z"


def _is_confusable_script(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _CONFUSABLE_SCRIPT_RANGES)


def _iter_word_tokens(text: str):
    """Yield maximal runs of letter/mark/number characters (word tokens).

    Tokens split on whitespace, punctuation, underscores, and any char
    that is not a letter (L*), mark (M*), or number (N*) -- so digits and
    combining marks stay glued to the surrounding letters.
    """
    token: list[str] = []
    for c in text:
        if unicodedata.category(c)[0] in ("L", "M", "N"):
            token.append(c)
        elif token:
            yield "".join(token)
            token = []
    if token:
        yield "".join(token)


class ContentScanError(ValueError):
    """Raised when content scanning detects a suspicious pattern."""

    def __init__(self, category: str, detail: str) -> None:
        self.category = category
        self.detail = detail
        super().__init__(f"Content scan rejected ({category}): {detail}")


def scan_content(text: str) -> None:
    """Scan text for prompt injection, credentials, exfiltration, invisible
    chars, and script-mixing confusables.

    Invisible-character detection runs on the RAW text (pre-normalization)
    to catch codepoints NFC could strip or alter. All other checks run on
    NFC-normalized text so canonically-equivalent sequences (e.g. a letter
    plus combining accent) reach the regexes in composed form. NFC does
    NOT fold confusable lookalikes -- Cyrillic 'о' stays Cyrillic -- so
    homographic bypass is handled by a separate script-mixing check:

    any word token containing both ASCII Latin letters and Cyrillic or
    Greek codepoints is rejected. This is a heuristic, not full Unicode
    confusable detection: it covers Cyrillic (all blocks) and Greek
    (basic + extended) mixed into Latin tokens only. A token written
    entirely in lookalike codepoints of one script (e.g. all-Cyrillic
    'іgnоrе'), and confusable scripts outside the listed ranges
    (fullwidth forms, Cherokee, Armenian, ...), are NOT detected.

    Raises ContentScanError if suspicious content is detected.
    Scans all text fields that flow into the ledger and ultimately into
    boot context for other agents.
    """
    # 0. Check invisible chars on RAW text (before normalization strips them)
    found_invisible = [c for c in text if _is_invisible_char(c)]
    if found_invisible:
        codepoints = ", ".join(f"U+{ord(c):04X}" for c in set(found_invisible))
        raise ContentScanError(
            "invisible_unicode",
            f"Contains invisible Unicode characters: {codepoints}",
        )

    # Normalize to NFC: canonical composition only -- does NOT fold confusables.
    normalized = unicodedata.normalize("NFC", text)

    # Script-mixing homoglyph check: a token combining ASCII Latin with
    # Cyrillic/Greek codepoints (e.g. 'ignоre' with Cyrillic о) is the
    # signature of regex-evading injection. Monolingual non-Latin tokens
    # and script-mixing ACROSS tokens are legitimate and pass.
    for token in _iter_word_tokens(normalized):
        has_latin = any(_is_ascii_latin(c) for c in token)
        if not has_latin:
            continue
        if any(_is_confusable_script(ord(c)) for c in token):
            raise ContentScanError(
                "script_mixing",
                f"Token mixes ASCII Latin with Cyrillic/Greek: {token!r}",
            )

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
    """Resolve HMAC signing secret from BUS_SIGNING_SECRET env var.

    Returns the secret as bytes if set and 32+ bytes long, otherwise None.
    Does NOT enforce fail-closed -- callers are responsible for checking
    ``_allow_unsigned()`` when a secret is unavailable.
    """
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


def _allow_unsigned() -> bool:
    """Return True if unsigned ledger writes are allowed (tests/dev only).

    Default: False (fail-closed). Set CLP_ALLOW_UNSIGNED=1 to bypass.
    Closes the prior fail-open default where a missing secret silently
    produced unsigned entries that could be forged.
    """
    allow = os.environ.get("CLP_ALLOW_UNSIGNED", "").strip().lower()
    return allow in ("1", "true", "yes", "on")


def _resolve_federation_secret() -> bytes | None:
    """Resolve federation verification secret from environment.

    Checks FEDERATION_SECRET first, then falls back to BUS_SIGNING_SECRET.
    Returns the secret as bytes if set and 32+ bytes long, otherwise None.
    """
    for var in ("FEDERATION_SECRET", "BUS_SIGNING_SECRET"):
        raw = os.environ.get(var)
        if not raw:
            continue
        secret_bytes = raw.encode("utf-8")
        if len(secret_bytes) < 32:
            logger.warning(
                "%s too short (%d bytes, need 32+).",
                var,
                len(secret_bytes),
            )
            continue
        return secret_bytes
    return None


def _sign_entry(entry_jsonl: str, secret: bytes) -> str:
    """Compute HMAC-SHA256 signature of a JSONL line."""
    return hmac.new(
        secret, entry_jsonl.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_entry_signature(entry: LedgerEntry, secret: bytes) -> bool:
    """Verify the HMAC-SHA256 signature of a ledger entry.

    Returns True if the signature is present and valid, False otherwise.
    Uses ``hmac.compare_digest`` for constant-time comparison to prevent
    timing attacks.

    Parameters
    ----------
    entry : LedgerEntry
        The entry whose signature to verify.
    secret : bytes
        The HMAC-SHA256 key (32+ bytes).

    Returns:
    -------
    bool
        True if signature is valid, False if missing or mismatched.
    """
    if not entry.signature:
        return False
    # Reconstruct unsigned JSONL to verify
    d = entry.to_dict()
    d.pop("signature", None)
    unsigned_entry = LedgerEntry.from_dict({**d, "signature": None})
    unsigned_jsonl = unsigned_entry.to_jsonl()
    expected_sig = _sign_entry(unsigned_jsonl, secret)
    return hmac.compare_digest(entry.signature, expected_sig)


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

    # Scan content for injection, credentials, exfiltration, invisible
    # chars, and script-mixing confusables. Covers every free-text field
    # (content, evidence, tags, agent, model) -- runs BEFORE hash
    # verification to reject poisoned content early.
    scan_content(entry.content)
    if entry.evidence:
        scan_content(entry.evidence)
    if entry.tags:
        scan_content(" ".join(entry.tags))
    if entry.agent:
        scan_content(entry.agent)
    if entry.model:
        scan_content(entry.model)

    # Verify content hash
    if not entry.verify_hash():
        raise ValueError(
            "Content hash mismatch: entry content_hash does not match "
            "computed hash of content fields"
        )

    # Resolve signing secret
    if secret is None:
        secret = _resolve_signing_secret()

    # CLP-001: Fail-closed if no signing secret in production.
    # Entries must be signed to prevent forgery. Set CLP_ALLOW_UNSIGNED=1
    # to bypass (tests/dev only).
    if secret is None and not _allow_unsigned():
        raise ValueError(
            "HMAC signing required but no secret available. "
            "Set BUS_SIGNING_SECRET (32+ bytes) or CLP_ALLOW_UNSIGNED=1 "
            "for tests."
        )

    # Sign if secret available.
    # CLP-001 (adversarial fix-up): Always re-sign with the local secret,
    # ignoring any caller-supplied signature. A pre-set signature (even a
    # forged one like "0"*64) would otherwise bypass signing and be persisted
    # to the append-only ledger untouched. Stripping it unconditionally
    # ensures post_entry always signs with the local secret.
    d = entry.to_dict()
    d["signature"] = None
    entry = LedgerEntry.from_dict(d)
    if secret is not None:
        jsonl_line = entry.to_jsonl()
        sig = _sign_entry(jsonl_line, secret)
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

    # Synchronize SQLite derived index (best effort, fail-open)
    try:
        from hummbl_clp.core.sqlite_indexer import index_single_entry
        db_path = path.parent / "index.db"
        index_single_entry(entry, db_path=db_path)
    except Exception as exc:
        logger.debug("Failed to update SQLite index: %s", exc)

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
                # strict=False: tolerate legacy schema drift in persisted
                # entries (non-clp- IDs, unknown vendors, missing content_hash)
                entry = LedgerEntry.from_dict(data, strict=False)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
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
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
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
                try:
                    sig_ok = verify_entry_signature(entry, secret)
                except TypeError as e:
                    errors.append(
                        f"Line {line_num}: signature type error for "
                        f"{entry.id}: {e}"
                    )
                    continue
                if not sig_ok:
                    errors.append(
                        f"Line {line_num}: signature mismatch for {entry.id}"
                    )
                    continue
            elif not entry.signature and secret and not _allow_unsigned():
                # CLP-001: Fail-closed on unsigned entries when a secret is
                # configured and unsigned writes are not explicitly allowed.
                # An attacker who writes directly to the ledger file (bypassing
                # post_entry) could otherwise inject unsigned entries that pass
                # integrity validation silently.
                errors.append(
                    f"Line {line_num}: unsigned entry {entry.id} rejected "
                    f"(secret configured but entry has no signature)"
                )
                continue

            valid_count += 1

    return valid_count, errors
