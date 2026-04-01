"""hummbl-clp -- Cognitive Ledger Protocol.

Vendor-agnostic shared memory for multi-agent AI coordination.

Three layers:
  1. Shared State  (state.json)  -- mutable snapshot of who's doing what
  2. Shared Memory (ledger.jsonl) -- append-only learning log
  3. Shared Intent (intent.md)    -- human-authored goals and priorities

Usage:
    from hummbl_clp import LedgerEntry, post_entry, read_entries
"""

from __future__ import annotations

from hummbl_clp.core.models import (
    AssuranceLevel,
    LedgerEntry,
    LedgerEntryType,
    LedgerScope,
    SharedState,
    VALID_VENDORS,
    compute_content_hash,
)
from hummbl_clp.core.ledger_writer import (
    ContentScanError,
    post_entry,
    read_entries,
    scan_content,
    validate_integrity,
)
from hummbl_clp.core.state_manager import (
    ConcurrencyError,
    claim_file,
    read_state,
    release_file,
    update_agent_status,
    write_state,
)
from hummbl_clp.core.query import (
    active_entries,
    latest_by_scope,
    query_entries,
    summarize_for_boot,
)
from hummbl_clp.core.schema_validator import (
    ValidationError,
    validate,
    validate_entry_dict,
    validate_file,
    validate_state_dict,
)
from hummbl_clp.core.indexer import BM25Index, tokenize
from hummbl_clp.core.verified_writer import (
    create_verified_entry,
    post_verified_entry,
    resolve_entry_identity,
)

__version__ = "0.1.0"

__all__ = [
    # Models
    "AssuranceLevel",
    "LedgerEntry",
    "LedgerEntryType",
    "LedgerScope",
    "SharedState",
    "VALID_VENDORS",
    "compute_content_hash",
    # Ledger writer
    "ContentScanError",
    "post_entry",
    "read_entries",
    "scan_content",
    "validate_integrity",
    # State manager
    "ConcurrencyError",
    "claim_file",
    "read_state",
    "release_file",
    "update_agent_status",
    "write_state",
    # Query
    "active_entries",
    "latest_by_scope",
    "query_entries",
    "summarize_for_boot",
    # Schema validator
    "ValidationError",
    "validate",
    "validate_entry_dict",
    "validate_file",
    "validate_state_dict",
    # Indexer
    "BM25Index",
    "tokenize",
    # Verified writer
    "create_verified_entry",
    "post_verified_entry",
    "resolve_entry_identity",
]
