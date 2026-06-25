"""Tests for CLP-001: HMAC signing fail-closed default in ledger_writer.

Covers:
- Fail-closed: post_entry raises ValueError when no secret and no bypass
- CLP_ALLOW_UNSIGNED=1 bypass allows unsigned writes (tests/dev only)
- Correct secret signs entries (signature populated)
- Short secret (<32 bytes) is rejected (warning, fail-closed)
- verify_entry_signature validates correct signatures
- verify_entry_signature rejects wrong/missing signatures
- hmac.compare_digest used for verification (structural guard)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hummbl_clp.core.ledger_writer import (
    _allow_unsigned,
    _resolve_federation_secret,
    _resolve_signing_secret,
    _sign_entry,
    post_entry,
    verify_entry_signature,
)
from hummbl_clp.core.models import LedgerEntry

# 32+ byte test secret
TEST_SECRET = b"a" * 32
TEST_SECRET_STR = "a" * 32
SHORT_SECRET_STR = "short"


def _make_entry() -> LedgerEntry:
    """Create a minimal valid ledger entry for testing."""
    return LedgerEntry.create(
        content="Test content for security validation",
        agent="test-agent",
        vendor="anthropic",
        model="test-model",
        entry_type="discovery",
        scope="project",
    )


class TestFailClosedDefault:
    """CLP-001: post_entry must fail-closed when no signing secret is set."""

    def test_post_entry_raises_without_secret(self, tmp_path, monkeypatch):
        """Without BUS_SIGNING_SECRET and without CLP_ALLOW_UNSIGNED,
        post_entry must raise ValueError."""
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        entry = _make_entry()
        with pytest.raises(ValueError, match="HMAC signing required"):
            post_entry(entry, ledger_path=tmp_path / "ledger.jsonl")

    def test_post_entry_raises_without_secret_explicit_none(self, tmp_path, monkeypatch):
        """Even with explicit secret=None, fail-closed applies."""
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        entry = _make_entry()
        with pytest.raises(ValueError, match="HMAC signing required"):
            post_entry(entry, ledger_path=tmp_path / "ledger.jsonl", secret=None)


class TestAllowUnsignedBypass:
    """CLP_ALLOW_UNSIGNED=1 bypasses fail-closed for tests/dev."""

    def test_allow_unsigned_env_var_bypass(self, tmp_path, monkeypatch):
        """CLP_ALLOW_UNSIGNED=1 allows unsigned writes."""
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        entry = _make_entry()
        result = post_entry(entry, ledger_path=tmp_path / "ledger.jsonl")
        assert result.signature is None  # unsigned but accepted

    def test_allow_unsigned_function_returns_false_by_default(self, monkeypatch):
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        assert _allow_unsigned() is False

    def test_allow_unsigned_function_returns_true_when_set(self, monkeypatch):
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        assert _allow_unsigned() is True

    def test_allow_unsigned_accepts_true_yes_on(self, monkeypatch):
        for val in ("true", "yes", "on", "TRUE", "Yes"):
            monkeypatch.setenv("CLP_ALLOW_UNSIGNED", val)
            assert _allow_unsigned() is True, f"CLP_ALLOW_UNSIGNED={val!r} should bypass"


class TestSigningWithSecret:
    """Entries are signed when a valid secret is available."""

    def test_post_entry_signs_with_env_secret(self, tmp_path, monkeypatch):
        """post_entry signs entries using BUS_SIGNING_SECRET env var."""
        monkeypatch.setenv("BUS_SIGNING_SECRET", TEST_SECRET_STR)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        entry = _make_entry()
        result = post_entry(entry, ledger_path=tmp_path / "ledger.jsonl")
        assert result.signature is not None
        assert len(result.signature) == 64  # SHA-256 hex

    def test_post_entry_signs_with_explicit_secret(self, tmp_path, monkeypatch):
        """post_entry signs entries using explicit secret parameter."""
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        entry = _make_entry()
        result = post_entry(
            entry, ledger_path=tmp_path / "ledger.jsonl", secret=TEST_SECRET
        )
        assert result.signature is not None
        assert len(result.signature) == 64

    def test_signed_entry_verifies(self, tmp_path, monkeypatch):
        """A signed entry should pass verify_entry_signature."""
        monkeypatch.setenv("BUS_SIGNING_SECRET", TEST_SECRET_STR)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        entry = _make_entry()
        result = post_entry(entry, ledger_path=tmp_path / "ledger.jsonl")
        assert verify_entry_signature(result, TEST_SECRET) is True


class TestShortSecretRejected:
    """Secrets shorter than 32 bytes are rejected."""

    def test_resolve_signing_secret_returns_none_for_short(self, monkeypatch):
        monkeypatch.setenv("BUS_SIGNING_SECRET", SHORT_SECRET_STR)
        assert _resolve_signing_secret() is None

    def test_post_entry_fails_closed_with_short_secret(self, tmp_path, monkeypatch):
        """Short secret -> None -> fail-closed (unless bypass set)."""
        monkeypatch.setenv("BUS_SIGNING_SECRET", SHORT_SECRET_STR)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        entry = _make_entry()
        with pytest.raises(ValueError, match="HMAC signing required"):
            post_entry(entry, ledger_path=tmp_path / "ledger.jsonl")


class TestVerifyEntrySignature:
    """verify_entry_signature correctness."""

    def test_verify_correct_signature(self):
        entry = _make_entry()
        jsonl = entry.to_jsonl()
        sig = _sign_entry(jsonl, TEST_SECRET)
        signed = LedgerEntry.from_dict({**entry.to_dict(), "signature": sig})
        assert verify_entry_signature(signed, TEST_SECRET) is True

    def test_verify_wrong_signature_rejected(self):
        entry = _make_entry()
        wrong_sig = "f" * 64  # wrong signature
        signed = LedgerEntry.from_dict({**entry.to_dict(), "signature": wrong_sig})
        assert verify_entry_signature(signed, TEST_SECRET) is False

    def test_verify_missing_signature_rejected(self):
        entry = _make_entry()
        assert entry.signature is None
        assert verify_entry_signature(entry, TEST_SECRET) is False

    def test_verify_wrong_secret_rejected(self):
        entry = _make_entry()
        jsonl = entry.to_jsonl()
        sig = _sign_entry(jsonl, TEST_SECRET)
        signed = LedgerEntry.from_dict({**entry.to_dict(), "signature": sig})
        # Different secret should not verify
        assert verify_entry_signature(signed, b"b" * 32) is False

    def test_compare_digest_used_for_verification(self):
        """Structural guard: hmac.compare_digest must be used."""
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "hummbl_clp"
            / "core"
            / "ledger_writer.py"
        )
        text = src.read_text(encoding="utf-8")
        assert "hmac.compare_digest" in text, (
            "ledger_writer must use hmac.compare_digest for verification"
        )


class TestResolveFederationSecret:
    """_resolve_federation_secret checks FEDERATION_SECRET then BUS_SIGNING_SECRET."""

    def test_federation_secret_takes_priority(self, monkeypatch):
        fed = "f" * 32
        bus = "b" * 32
        monkeypatch.setenv("FEDERATION_SECRET", fed)
        monkeypatch.setenv("BUS_SIGNING_SECRET", bus)
        assert _resolve_federation_secret() == fed.encode("utf-8")

    def test_federation_secret_falls_back_to_bus(self, monkeypatch):
        bus = "b" * 32
        monkeypatch.delenv("FEDERATION_SECRET", raising=False)
        monkeypatch.setenv("BUS_SIGNING_SECRET", bus)
        assert _resolve_federation_secret() == bus.encode("utf-8")

    def test_federation_secret_none_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("FEDERATION_SECRET", raising=False)
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        assert _resolve_federation_secret() is None

    def test_federation_secret_rejects_short(self, monkeypatch):
        monkeypatch.setenv("FEDERATION_SECRET", "short")
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        assert _resolve_federation_secret() is None


class TestValidateIntegrityFailClosed:
    """validate_integrity must fail-closed on unsigned entries when a secret
    is configured and CLP_ALLOW_UNSIGNED is not set."""

    def test_validate_integrity_fail_closed_on_unsigned(self, tmp_path, monkeypatch):
        """An unsigned entry written directly to the ledger file (bypassing
        post_entry) must be flagged as an integrity failure when a secret is
        configured."""
        from hummbl_clp.core.ledger_writer import validate_integrity

        monkeypatch.setenv("BUS_SIGNING_SECRET", TEST_SECRET_STR)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)

        ledger = tmp_path / "ledger.jsonl"
        # Write an unsigned entry directly to the file, bypassing post_entry.
        entry = _make_entry()
        ledger.write_text(entry.to_jsonl() + "\n", encoding="utf-8")

        valid_count, errors = validate_integrity(
            ledger_path=ledger,
            secret=TEST_SECRET,
        )
        assert valid_count == 0
        assert len(errors) == 1
        assert "unsigned" in errors[0].lower()

    def test_validate_integrity_allows_unsigned_when_no_secret(self, tmp_path, monkeypatch):
        """Backwards compat: unsigned entries pass when no secret configured."""
        from hummbl_clp.core.ledger_writer import validate_integrity

        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)

        ledger = tmp_path / "ledger.jsonl"
        entry = _make_entry()
        ledger.write_text(entry.to_jsonl() + "\n", encoding="utf-8")

        valid_count, errors = validate_integrity(
            ledger_path=ledger,
            secret=None,
        )
        assert valid_count == 1
        assert errors == []

    def test_validate_integrity_allows_unsigned_with_bypass(self, tmp_path, monkeypatch):
        """CLP_ALLOW_UNSIGNED=1 keeps backwards compat even with a secret."""
        from hummbl_clp.core.ledger_writer import validate_integrity

        monkeypatch.setenv("BUS_SIGNING_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")

        ledger = tmp_path / "ledger.jsonl"
        entry = _make_entry()
        ledger.write_text(entry.to_jsonl() + "\n", encoding="utf-8")

        valid_count, errors = validate_integrity(
            ledger_path=ledger,
            secret=TEST_SECRET,
        )
        assert valid_count == 1
        assert errors == []


# ---------------------------------------------------------------------------
# Adversarial fix-up: pre-signed entry bypass & non-string signature DoS
# ---------------------------------------------------------------------------


class TestPreSignedEntryBypass:
    """CLP-001 (adversarial fix-up): post_entry must always re-sign with the
    local secret, ignoring any caller-supplied (possibly forged) signature."""

    def test_post_entry_re_signs_pre_signed_entry(self, tmp_path, monkeypatch):
        """An entry passed with a forged signature (e.g. "0"*64) must be
        re-signed with the local secret; the forged value must NOT persist."""
        monkeypatch.setenv("BUS_SIGNING_SECRET", TEST_SECRET_STR)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)

        entry = _make_entry()
        forged_sig = "0" * 64
        forged = LedgerEntry.from_dict({**entry.to_dict(), "signature": forged_sig})
        assert forged.signature == forged_sig  # sanity: forged value present

        result = post_entry(forged, ledger_path=tmp_path / "ledger.jsonl")
        # The written signature must match the local secret's HMAC, NOT the
        # forged value.
        assert result.signature != forged_sig
        assert result.signature is not None
        assert len(result.signature) == 64
        assert verify_entry_signature(result, TEST_SECRET) is True

    def test_post_entry_re_signs_pre_signed_entry_with_bypass(self, tmp_path, monkeypatch):
        """With CLP_ALLOW_UNSIGNED=1 and a secret configured, a pre-signed
        entry must still be re-signed (forged signature stripped/replaced)."""
        monkeypatch.setenv("BUS_SIGNING_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")

        entry = _make_entry()
        forged_sig = "deadbeef" * 8  # 64 hex chars, clearly forged
        forged = LedgerEntry.from_dict({**entry.to_dict(), "signature": forged_sig})

        result = post_entry(forged, ledger_path=tmp_path / "ledger.jsonl")
        # The forged signature must NOT be preserved. With a secret present,
        # post_entry re-signs; the result must verify against the local secret.
        assert result.signature != forged_sig
        assert verify_entry_signature(result, TEST_SECRET) is True


class TestNonStringSignature:
    """CLP-001 (adversarial fix-up): non-string signatures must not crash
    verify_entry_signature or ingest/validate loops (DoS vector)."""

    def test_verify_entry_signature_handles_non_string_signature(self):
        """A non-string signature (e.g. 123) must be rejected at
        LedgerEntry construction (ValueError) rather than crashing
        verify_entry_signature with TypeError."""
        entry = _make_entry()
        d = entry.to_dict()
        d["signature"] = 123  # non-string, would crash compare_digest
        with pytest.raises(ValueError, match="signature must be a str or None"):
            LedgerEntry.from_dict(d)

    def test_non_string_signature_rejected_in_post_init_bool(self):
        """A boolean signature must also be rejected at construction."""
        entry = _make_entry()
        d = entry.to_dict()
        d["signature"] = True
        with pytest.raises(ValueError, match="signature must be a str or None"):
            LedgerEntry.from_dict(d)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
