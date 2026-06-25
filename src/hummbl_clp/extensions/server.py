"""Open Brain HTTP Server -- serves the knowledge compiler over the network.

Endpoints:
    GET  /status          -- index stats, uptime, entry count
    POST /search          -- unified search across all memory pools
    POST /reindex         -- rebuild index from ledger
    POST /ingest          -- accept entries from remote brains (federation)
    POST /consolidate     -- run ledger consolidation (with file lock)
    GET  /health          -- simple health check

Stdlib-only (http.server).
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

from hummbl_clp.extensions.consolidator import run_consolidation
from hummbl_clp.core.indexer import BM25Index
from hummbl_clp.extensions.retriever import OpenBrainRetriever

logger = logging.getLogger(__name__)

DEFAULT_PORT = 11435
DEFAULT_HOST = "127.0.0.1"

# Max request body size (1 MB)
MAX_REQUEST_BODY = 1_048_576


def _require_auth() -> bool:
    """Return True if auth is required (fail-closed when token not configured).

    Default: True (fail-closed). Set CLP_ALLOW_NO_AUTH=1 to bypass
    (tests/dev only). Closes the prior fail-open default where a missing
    token silently accepted unauthenticated reads/writes.
    """
    allow = os.environ.get("CLP_ALLOW_NO_AUTH", "").strip().lower()
    return allow not in ("1", "true", "yes", "on")


class OpenBrainState:
    """Shared state for the server."""

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        ledger_path: str | Path | None = None,
    ) -> None:
        self.index = BM25Index()
        self.retriever = OpenBrainRetriever(state_dir=state_dir, index=self.index)
        self.ledger_path = ledger_path
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.request_count = 0
        self.lock = threading.Lock()

        self._reindex()

    def _reindex(self) -> int:
        """Rebuild index from ledger."""
        count = self.index.build(ledger_path=self.ledger_path)
        self.retriever._index_loaded = True
        try:
            self.index.save()
        except OSError as e:
            logger.warning("Could not save index: %s", e)
        return count

    def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute a search."""
        with self.lock:
            self.request_count += 1

        results = self.retriever.search(
            params.get("query", ""),
            token_budget=params.get("token_budget", 2000),
            scope=params.get("scope"),
            entry_type=params.get("entry_type"),
            since=params.get("since"),
            sources=params.get("sources"),
            agent=params.get("agent", "remote"),
            limit=params.get("limit", 20),
        )
        return [r.to_dict() for r in results]

    def status(self) -> dict[str, Any]:
        """Return server status."""
        return {
            "service": "open-brain",
            "version": "0.1.0",
            "started_at": self.started_at,
            "request_count": self.request_count,
            "index": {
                "total_docs": self.index.total_docs,
                "term_count": len(self.index.inverted_index),
                "avg_doc_length": round(self.index.avg_doc_length, 1),
                "built_at": self.index.built_at,
            },
        }

    def reindex(self) -> dict[str, Any]:
        """Rebuild index."""
        count = self._reindex()
        return {
            "reindexed": True,
            "entry_count": count,
            "built_at": self.index.built_at,
        }

    def ingest(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Ingest entries from a remote brain (federation).

        CLP-003: All incoming entries must carry a valid HMAC-SHA256
        signature verified against FEDERATION_SECRET (or BUS_SIGNING_SECRET
        as fallback). Unsigned or invalid-signature entries are rejected.
        """
        from hummbl_clp.core.ledger_writer import (
            _allow_unsigned,
            _resolve_federation_secret,
            post_entry,
            verify_entry_signature,
        )
        from hummbl_clp.core.models import LedgerEntry

        # Resolve the federation verification secret
        fed_secret = _resolve_federation_secret()

        # If no secret is available, we cannot verify any signatures.
        # Fail-closed unless CLP_ALLOW_UNSIGNED=1 is set (tests/dev only).
        if fed_secret is None and not _allow_unsigned():
            return {
                "ingested": 0,
                "errors": [
                    "Federation secret not configured (FEDERATION_SECRET or "
                    "BUS_SIGNING_SECRET required for signature verification)"
                ],
            }

        ingested = 0
        errors = []
        for entry_data in entries:
            try:
                # CLP-003: Require a full signed entry for federation.
                # Entries without id/content_hash are created locally and
                # cannot carry a verifiable signature from the remote brain.
                if "id" not in entry_data or "content_hash" not in entry_data:
                    errors.append(
                        "Federation entries must include id and content_hash "
                        "(full signed entry required)"
                    )
                    continue

                # Create entry from the original data for signature verification.
                # The signature covers the entry as received, BEFORE we add the
                # "remote-ingest" tag. Modifying tags before verification would
                # invalidate the signature.
                entry = LedgerEntry.from_dict(entry_data)

                # CLP-003: Verify HMAC signature on incoming entries.
                # Reject unsigned entries to prevent forged identity injection.
                if fed_secret is not None:
                    if not entry.signature:
                        errors.append(
                            f"Entry {entry.id} rejected: unsigned entries "
                            f"not allowed via federation"
                        )
                        continue
                    if not verify_entry_signature(entry, fed_secret):
                        errors.append(
                            f"Entry {entry.id} rejected: signature "
                            f"verification failed"
                        )
                        continue

                # Add "remote-ingest" tag after signature verification.
                tags = list(entry_data["tags"]) if "tags" in entry_data else []
                if "remote-ingest" not in tags:
                    tags.append("remote-ingest")
                entry_data["tags"] = tags
                # CLP-003: Strip the remote signature before reconstruction.
                # The tag modification invalidates the original signature, and
                # post_entry must re-sign with the local secret so the written
                # entry's signature matches its JSONL representation. Leaving
                # the stale signature would cause validate_integrity() to flag
                # every federated entry as a signature mismatch.
                entry_data["signature"] = None
                # Reconstruct entry with updated tags for writing
                entry = LedgerEntry.from_dict(entry_data)

                post_entry(entry, ledger_path=self.ledger_path)
                ingested += 1
            except (ValueError, KeyError, TypeError) as e:
                errors.append(str(e))

        if ingested > 0:
            self._reindex()

        return {
            "ingested": ingested,
            "errors": errors[:10],
        }

    def consolidate(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Run ledger consolidation with a file lock."""
        lock_dir = Path(self.ledger_path).parent if self.ledger_path else Path("_state/cognition")
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "consolidator.lock"

        lock_fd = None
        try:
            lock_fd = open(lock_path, "w")
            if fcntl is not None:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if lock_fd is not None:
                lock_fd.close()
            return {"error": "consolidation already in progress"}

        try:
            result = run_consolidation(
                ledger_path=self.ledger_path,
                dry_run=dry_run,
            )
            if not dry_run and result.get("consolidated", 0) > 0:
                self._reindex()
            return result
        finally:
            if fcntl is not None:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            lock_fd.close()


def _make_handler(state: OpenBrainState, *, auth_token: str | None = None) -> type:
    """Create a request handler class with access to shared state."""

    class OpenBrainHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            logger.info(format, *args)

        def _send_json(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_auth(self) -> bool:
            # CLP-002: Fail-closed when no auth token is configured.
            # Prior default allowed unauthenticated access to all endpoints.
            if not auth_token:
                if _require_auth():
                    self._send_json(
                        {"error": "unauthorized: OPEN_BRAIN_TOKEN not configured"},
                        401,
                    )
                    return False
                # CLP_ALLOW_NO_AUTH=1 bypass (tests/dev only)
                return True
            header = self.headers.get("Authorization", "")
            expected = f"Bearer {auth_token}"
            if hmac.compare_digest(header, expected):
                return True
            self._send_json({"error": "unauthorized"}, 401)
            return False

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_REQUEST_BODY:
                return b""
            if length > 0:
                return self.rfile.read(length)
            return b""

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json({"status": "ok"})
            elif self.path == "/status":
                if not self._check_auth():
                    return
                self._send_json(state.status())
            else:
                self._send_json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            if not self._check_auth():
                return

            try:
                body = self._read_body()
                params = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, 400)
                return

            if self.path == "/search":
                if "query" not in params:
                    self._send_json({"error": "missing 'query' field"}, 400)
                    return
                results = state.search(params)
                self._send_json({"results": results, "count": len(results)})

            elif self.path == "/reindex":
                result = state.reindex()
                self._send_json(result)

            elif self.path == "/ingest":
                entries = params.get("entries", [])
                if not entries:
                    self._send_json({"error": "missing 'entries' field"}, 400)
                    return
                result = state.ingest(entries)
                self._send_json(result)

            elif self.path == "/consolidate":
                dry_run = params.get("dry_run", False)
                result = state.consolidate(dry_run=dry_run)
                self._send_json(result)

            else:
                self._send_json({"error": "not found"}, 404)

    return OpenBrainHandler


def run_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    state_dir: str | Path | None = None,
    ledger_path: str | Path | None = None,
    auth_token: str | None = None,
) -> None:
    """Start the Open Brain HTTP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    token = auth_token or os.environ.get("OPEN_BRAIN_TOKEN")
    if token:
        logger.info("Bearer token auth enabled")
    else:
        # CLP-002: Fail-closed default. The server will reject all
        # authenticated endpoints with 401 unless CLP_ALLOW_NO_AUTH=1
        # is set (tests/dev only).
        if _require_auth():
            logger.warning(
                "No OPEN_BRAIN_TOKEN configured -- server will reject "
                "all requests with 401 (fail-closed). Set OPEN_BRAIN_TOKEN "
                "or CLP_ALLOW_NO_AUTH=1 for tests."
            )
        else:
            logger.warning(
                "No auth token configured -- CLP_ALLOW_NO_AUTH=1 bypass "
                "active (tests/dev only)"
            )

    logger.info("Initializing Open Brain...")
    brain_state = OpenBrainState(state_dir=state_dir, ledger_path=ledger_path)
    logger.info(
        "Index ready: %d entries, %d terms",
        brain_state.index.total_docs,
        len(brain_state.index.inverted_index),
    )

    handler = _make_handler(brain_state, auth_token=token)
    server = HTTPServer((host, port), handler)
    logger.info("Open Brain listening on %s:%d", host, port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open Brain HTTP Server -- knowledge compiler for multi-agent systems",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--bind", help="host:port shorthand")
    parser.add_argument("--state-dir", help="Override state directory")
    parser.add_argument("--ledger", help="Override ledger path")

    args = parser.parse_args(argv)

    host = args.host
    port = args.port
    if args.bind:
        parts = args.bind.rsplit(":", 1)
        host = parts[0]
        if len(parts) > 1:
            port = int(parts[1])

    run_server(
        host=host,
        port=port,
        state_dir=args.state_dir,
        ledger_path=args.ledger,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
