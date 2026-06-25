"""Tests for CLP-002: HTTP server fail-closed auth and CLP-003: federation
ingest signature verification.

Covers CLP-002 (server auth):
- Fail-closed: requests rejected with 401 when no token configured
- Correct Bearer token accepted
- Wrong token rejected
- Missing Authorization header rejected
- CLP_ALLOW_NO_AUTH=1 bypass works for tests/dev
- hmac.compare_digest used for auth (structural guard)

Covers CLP-003 (federation ingest):
- Unsigned entries rejected via federation endpoint
- Signed entries with valid signature accepted
- Signed entries with wrong signature rejected
- Fail-closed when no federation secret configured
- CLP_ALLOW_UNSIGNED=1 bypass allows unsigned federation entries
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hummbl_clp.core.ledger_writer import _sign_entry
from hummbl_clp.core.models import LedgerEntry
from hummbl_clp.extensions.server import OpenBrainState, _require_auth
from hummbl_clp.extensions.server import _make_handler as _make_handler_cls

TEST_SECRET = b"a" * 32
TEST_SECRET_STR = "a" * 32
TEST_TOKEN = "test-token-abc123def456"


def _make_entry_dict() -> dict:
    """Create a minimal valid ledger entry dict for federation tests."""
    entry = LedgerEntry.create(
        content="Federation test content",
        agent="remote-agent",
        vendor="anthropic",
        model="remote-model",
        entry_type="discovery",
        scope="project",
    )
    return entry.to_dict()


def _sign_entry_dict(entry_dict: dict, secret: bytes = TEST_SECRET) -> dict:
    """Sign an entry dict and return it with the signature field set."""
    entry = LedgerEntry.from_dict(entry_dict)
    jsonl = entry.to_jsonl()
    sig = _sign_entry(jsonl, secret)
    entry_dict["signature"] = sig
    return entry_dict


# ---------------------------------------------------------------------------
# Handler helpers
# ---------------------------------------------------------------------------


def _make_handler(
    state: OpenBrainState,
    *,
    method: str = "GET",
    path: str = "/status",
    body: dict | None = None,
    headers: dict | None = None,
    auth_token: str | None = None,
):
    """Construct an OpenBrainHandler with a fake request."""
    encoded = b""
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")

    all_headers: dict = {}
    if body is not None:
        all_headers["Content-Length"] = str(len(encoded))
    if headers:
        all_headers.update(headers)

    handler_cls = _make_handler_cls(state, auth_token=auth_token)
    handler = object.__new__(handler_cls)
    handler.path = path
    handler.headers = all_headers
    handler.rfile = io.BytesIO(encoded)
    handler.wfile = io.BytesIO()
    handler._response_code = None
    handler._response_body = None

    def _send_response(code, *args, **kwargs):
        handler._response_code = code

    def _send_header(*args, **kwargs):
        pass

    def _end_headers(*args, **kwargs):
        pass

    def _send_json(data, status=200):
        handler._response_code = status
        handler._response_body = data

    handler.send_response = _send_response
    handler.send_header = _send_header
    handler.end_headers = _end_headers
    handler._send_json = _send_json
    return handler


def _make_state(tmp_path) -> OpenBrainState:
    """Create an OpenBrainState with a temp ledger path."""
    # Mock _reindex to avoid needing a real index
    with mock.patch.object(OpenBrainState, "_reindex", return_value=0):
        with mock.patch("hummbl_clp.extensions.server.OpenBrainRetriever"):
            with mock.patch("hummbl_clp.extensions.server.BM25Index"):
                state = OpenBrainState.__new__(OpenBrainState)
                state.index = mock.MagicMock()
                state.index.total_docs = 0
                state.index.inverted_index = {}
                state.index.avg_doc_length = 0.0
                state.index.built_at = None
                state.retriever = mock.MagicMock()
                state.ledger_path = str(tmp_path / "ledger.jsonl")
                state.started_at = "2026-01-01T00:00:00Z"
                state.request_count = 0
                state.lock = __import__("threading").Lock()
    return state


# ---------------------------------------------------------------------------
# CLP-002: Server auth tests
# ---------------------------------------------------------------------------


class TestServerFailClosedDefault:
    """CLP-002: server must fail-closed when no token is configured."""

    def test_get_status_rejected_without_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPEN_BRAIN_TOKEN", raising=False)
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        state = _make_state(tmp_path)
        handler = _make_handler(state, path="/status", auth_token=None)
        handler.do_GET()
        assert handler._response_code == 401

    def test_post_search_rejected_without_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPEN_BRAIN_TOKEN", raising=False)
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        state = _make_state(tmp_path)
        handler = _make_handler(
            state,
            method="POST",
            path="/search",
            body={"query": "test"},
            auth_token=None,
        )
        handler.do_POST()
        assert handler._response_code == 401

    def test_health_endpoint_no_auth_required(self, tmp_path, monkeypatch):
        """Health endpoint should remain accessible without auth."""
        monkeypatch.delenv("OPEN_BRAIN_TOKEN", raising=False)
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        state = _make_state(tmp_path)
        handler = _make_handler(state, path="/health", auth_token=None)
        handler.do_GET()
        assert handler._response_code == 200


class TestServerBearerAuth:
    """Bearer token auth with constant-time comparison."""

    def test_correct_token_accepted(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        state = _make_state(tmp_path)
        handler = _make_handler(
            state,
            path="/status",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            auth_token=TEST_TOKEN,
        )
        handler.do_GET()
        assert handler._response_code == 200

    def test_wrong_token_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        state = _make_state(tmp_path)
        handler = _make_handler(
            state,
            path="/status",
            headers={"Authorization": "Bearer wrong-token"},
            auth_token=TEST_TOKEN,
        )
        handler.do_GET()
        assert handler._response_code == 401

    def test_missing_authorization_header_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        state = _make_state(tmp_path)
        handler = _make_handler(
            state,
            path="/status",
            auth_token=TEST_TOKEN,
        )
        handler.do_GET()
        assert handler._response_code == 401

    def test_malformed_authorization_header_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        state = _make_state(tmp_path)
        handler = _make_handler(
            state,
            path="/status",
            headers={"Authorization": "Basic abc123"},
            auth_token=TEST_TOKEN,
        )
        handler.do_GET()
        assert handler._response_code == 401

    def test_compare_digest_used_for_auth(self):
        """Structural guard: hmac.compare_digest must be used in server."""
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "hummbl_clp"
            / "extensions"
            / "server.py"
        )
        text = src.read_text(encoding="utf-8")
        assert "hmac.compare_digest" in text, (
            "server must use hmac.compare_digest for auth"
        )


class TestServerAllowNoAuthBypass:
    """CLP_ALLOW_NO_AUTH=1 bypasses fail-closed for tests/dev."""

    def test_allow_no_auth_bypasses_auth(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPEN_BRAIN_TOKEN", raising=False)
        monkeypatch.setenv("CLP_ALLOW_NO_AUTH", "1")
        state = _make_state(tmp_path)
        handler = _make_handler(state, path="/status", auth_token=None)
        handler.do_GET()
        assert handler._response_code == 200

    def test_require_auth_returns_false_when_bypass_set(self, monkeypatch):
        monkeypatch.setenv("CLP_ALLOW_NO_AUTH", "1")
        assert _require_auth() is False

    def test_require_auth_returns_true_by_default(self, monkeypatch):
        monkeypatch.delenv("CLP_ALLOW_NO_AUTH", raising=False)
        assert _require_auth() is True

    def test_require_auth_accepts_true_yes_on(self, monkeypatch):
        for val in ("true", "yes", "on", "TRUE", "Yes"):
            monkeypatch.setenv("CLP_ALLOW_NO_AUTH", val)
            assert _require_auth() is False, (
                f"CLP_ALLOW_NO_AUTH={val!r} should bypass"
            )


# ---------------------------------------------------------------------------
# CLP-003: Federation ingest signature verification tests
# ---------------------------------------------------------------------------


class TestFederationIngestSignature:
    """CLP-003: federation ingest must verify HMAC signatures."""

    def test_signed_entry_accepted(self, tmp_path, monkeypatch):
        """A properly signed entry should be ingested successfully."""
        monkeypatch.setenv("FEDERATION_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")  # allow post_entry to write
        state = _make_state(tmp_path)

        entry_dict = _sign_entry_dict(_make_entry_dict())
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry",
                return_value=LedgerEntry.from_dict(entry_dict),
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 1
        assert result["errors"] == []
        mock_post.assert_called_once()

    def test_unsigned_entry_rejected(self, tmp_path, monkeypatch):
        """Unsigned entries must be rejected via federation."""
        monkeypatch.setenv("FEDERATION_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        state = _make_state(tmp_path)

        entry_dict = _make_entry_dict()
        # No signature field
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry"
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 0
        assert len(result["errors"]) == 1
        assert "unsigned" in result["errors"][0].lower()
        mock_post.assert_not_called()

    def test_wrong_signature_rejected(self, tmp_path, monkeypatch):
        """Entries with invalid signatures must be rejected."""
        monkeypatch.setenv("FEDERATION_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        state = _make_state(tmp_path)

        entry_dict = _make_entry_dict()
        entry_dict["signature"] = "f" * 64  # wrong signature
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry"
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 0
        assert len(result["errors"]) == 1
        assert "signature" in result["errors"][0].lower()
        mock_post.assert_not_called()

    def test_signature_verified_with_different_secret(self, tmp_path, monkeypatch):
        """Entry signed with secret A should fail when server uses secret B."""
        secret_a = b"a" * 32
        secret_b = b"b" * 32
        monkeypatch.setenv("FEDERATION_SECRET", secret_b.decode())
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        state = _make_state(tmp_path)

        entry_dict = _sign_entry_dict(_make_entry_dict(), secret=secret_a)
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry"
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 0
        assert len(result["errors"]) == 1
        mock_post.assert_not_called()

    def test_fail_closed_when_no_federation_secret(self, tmp_path, monkeypatch):
        """When no federation secret is configured, reject all entries."""
        monkeypatch.delenv("FEDERATION_SECRET", raising=False)
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)
        state = _make_state(tmp_path)

        entry_dict = _make_entry_dict()
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry"
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 0
        assert len(result["errors"]) == 1
        assert "secret" in result["errors"][0].lower()
        mock_post.assert_not_called()

    def test_bypass_allows_unsigned_federation(self, tmp_path, monkeypatch):
        """CLP_ALLOW_UNSIGNED=1 allows unsigned entries when no secret set."""
        monkeypatch.delenv("FEDERATION_SECRET", raising=False)
        monkeypatch.delenv("BUS_SIGNING_SECRET", raising=False)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        state = _make_state(tmp_path)

        entry_dict = _make_entry_dict()
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry",
                return_value=LedgerEntry.from_dict(entry_dict),
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 1
        assert result["errors"] == []
        mock_post.assert_called_once()

    def test_entry_without_id_rejected(self, tmp_path, monkeypatch):
        """Entries without id/content_hash are rejected (full entry required)."""
        monkeypatch.setenv("FEDERATION_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        state = _make_state(tmp_path)

        # Entry with content but no id/content_hash
        entry_data = {
            "content": "test content",
            "agent": "remote",
            "vendor": "anthropic",
            "model": "test",
            "type": "discovery",
            "scope": "project",
        }
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry"
            ) as mock_post:
                result = state.ingest([entry_data])
        assert result["ingested"] == 0
        assert len(result["errors"]) == 1
        assert "id" in result["errors"][0].lower() or "full" in result["errors"][0].lower()
        mock_post.assert_not_called()

    def test_federation_uses_bus_signing_secret_fallback(self, tmp_path, monkeypatch):
        """Federation should fall back to BUS_SIGNING_SECRET if FEDERATION_SECRET not set."""
        monkeypatch.delenv("FEDERATION_SECRET", raising=False)
        monkeypatch.setenv("BUS_SIGNING_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        state = _make_state(tmp_path)

        entry_dict = _sign_entry_dict(_make_entry_dict())
        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry",
                return_value=LedgerEntry.from_dict(entry_dict),
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 1
        assert result["errors"] == []
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# CLP-003: Federated entry integrity after ingest (integration test)
# ---------------------------------------------------------------------------


class TestFederationIngestIntegrity:
    """Integration test: federated entries must pass validate_integrity after
    ingest, because post_entry re-signs them with the local secret."""

    def test_federated_entry_integrity_after_ingest(self, tmp_path, monkeypatch):
        """Write a federated entry through the REAL post_entry path (no mock)
        and confirm validate_integrity passes with no false positives."""
        from hummbl_clp.core.ledger_writer import validate_integrity

        # Local signing secret (used by post_entry to re-sign)
        local_secret = b"l" * 32
        monkeypatch.setenv("BUS_SIGNING_SECRET", local_secret.decode())
        # Federation secret used to verify the incoming remote signature
        fed_secret = b"f" * 32
        monkeypatch.setenv("FEDERATION_SECRET", fed_secret.decode())
        monkeypatch.delenv("CLP_ALLOW_UNSIGNED", raising=False)

        state = _make_state(tmp_path)

        # Build a remote entry signed with the federation secret
        entry_dict = _sign_entry_dict(_make_entry_dict(), secret=fed_secret)

        # Ingest through the real write path -- do NOT mock post_entry.
        with mock.patch.object(state, "_reindex"):
            result = state.ingest([entry_dict])
        assert result["ingested"] == 1
        assert result["errors"] == []

        # The federated entry should now be on disk, re-signed with the local
        # secret. validate_integrity must pass with zero errors.
        valid_count, errors = validate_integrity(
            ledger_path=state.ledger_path,
            secret=local_secret,
        )
        assert errors == [], f"integrity errors (stale signature?): {errors}"
        assert valid_count == 1


# ---------------------------------------------------------------------------
# Adversarial fix-up: non-string signature DoS in federation ingest
# ---------------------------------------------------------------------------


class TestFederationIngestNonStringSignature:
    """CLP-001 (adversarial fix-up): a federation entry with a non-string
    signature (e.g. 123) must not crash the ingest loop."""

    def test_ingest_handles_non_string_signature(self, tmp_path, monkeypatch):
        """A federation entry with "signature": 123 must be rejected with an
        error, not crash ingest with a TypeError."""
        monkeypatch.setenv("FEDERATION_SECRET", TEST_SECRET_STR)
        monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
        state = _make_state(tmp_path)

        entry_dict = _make_entry_dict()
        entry_dict["signature"] = 123  # non-string, would crash compare_digest

        with mock.patch.object(state, "_reindex"):
            with mock.patch(
                "hummbl_clp.core.ledger_writer.post_entry"
            ) as mock_post:
                result = state.ingest([entry_dict])
        assert result["ingested"] == 0
        assert len(result["errors"]) == 1
        # Must not have crashed; error captured gracefully.
        assert "signature" in result["errors"][0].lower() or "str" in result["errors"][0].lower()
        mock_post.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
