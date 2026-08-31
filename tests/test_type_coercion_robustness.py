"""Unit tests verifying type coercion and reader robustness in CLP models and ledger_writer."""
import json
import tempfile
from pathlib import Path
from hummbl_clp.core.models import LedgerEntry, compute_content_hash
from hummbl_clp.core.ledger_writer import read_entries

def test_ledger_entry_type_coercion():
    """Verify LedgerEntry coerces string tags, string confidence, and string links."""
    agent = "gemini (agent)"
    vendor = "google"
    model = "gemini-3.7-flash"
    entry_type = "DISCOVERY"
    scope = "PROJECT"
    content = "Type coercion test entry content."
    chash = compute_content_hash(
        agent=agent,
        vendor=vendor,
        model=model,
        entry_type="discovery",
        scope="project",
        content=content
    )

    data = {
        "id": "clp-aabbccddeeff",
        "timestamp": "2026-08-31T12:00:00Z",
        "agent": agent,
        "vendor": vendor,
        "model": model,
        "type": entry_type,
        "scope": scope,
        "content": content,
        "content_hash": chash,
        "confidence": "0.95",
        "tags": "governance, test-tag",
        "links": "clp-112233445566, clp-665544332211"
    }

    entry = LedgerEntry.from_dict(data)
    assert isinstance(entry.confidence, float)
    assert entry.confidence == 0.95
    assert isinstance(entry.tags, tuple)
    assert entry.tags == ("governance", "test-tag")
    assert isinstance(entry.links, tuple)
    assert entry.links == ("clp-112233445566", "clp-665544332211")
    assert entry.type == "discovery"
    assert entry.scope == "project"

def test_read_entries_with_malformed_and_coerced_lines():
    """Verify read_entries parses coerced lines and cleanly skips unrecoverable lines without crashing."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".jsonl") as f:
        temp_path = Path(f.name)
        
        valid_data = {
            "id": "clp-111122223333",
            "timestamp": "2026-08-31T12:00:00Z",
            "agent": "gemini (agent)",
            "vendor": "google",
            "model": "gemini-3.7-flash",
            "type": "DECISION",
            "scope": "PROJECT",
            "content": "Valid decision test.",
            "content_hash": compute_content_hash(
                agent="gemini (agent)",
                vendor="google",
                model="gemini-3.7-flash",
                entry_type="decision",
                scope="project",
                content="Valid decision test."
            ),
            "confidence": "0.85",
            "tags": "core, sync"
        }
        f.write(json.dumps(valid_data) + "\n")
        f.write('{"id": 12345, "invalid": true}\n')
        
        valid_data2 = {
            "id": "clp-444455556666",
            "timestamp": "2026-08-31T12:05:00Z",
            "agent": "gemini (agent)",
            "vendor": "google",
            "model": "gemini-3.7-flash",
            "type": "lesson",
            "scope": "module",
            "content": "Valid lesson test.",
            "content_hash": compute_content_hash(
                agent="gemini (agent)",
                vendor="google",
                model="gemini-3.7-flash",
                entry_type="lesson",
                scope="module",
                content="Valid lesson test."
            ),
            "confidence": 0.90,
            "tags": ["insight"]
        }
        f.write(json.dumps(valid_data2) + "\n")

    try:
        entries = read_entries(ledger_path=temp_path)
        assert len(entries) == 2
        assert entries[0].id == "clp-444455556666"
        assert entries[1].id == "clp-111122223333"
        assert entries[1].tags == ("core", "sync")
        assert entries[1].confidence == 0.85
    finally:
        if temp_path.exists():
            temp_path.unlink()
