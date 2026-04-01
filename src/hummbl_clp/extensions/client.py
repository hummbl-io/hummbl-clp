"""Open Brain Client -- query the remote brain from any machine.

Connects to the Open Brain server on any host via HTTP.
Stdlib-only.

Usage:
    from hummbl_clp.extensions.client import OpenBrainClient

    brain = OpenBrainClient()  # Uses OPEN_BRAIN_URL env or default
    results = brain.search("OAuth token refresh")
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.client import HTTPConnection
from typing import Any
from urllib.parse import urlparse

DEFAULT_URL = "http://127.0.0.1:11435"

# Max response body to read (10 MB)
MAX_RESPONSE_SIZE = 10 * 1_048_576


class OpenBrainClient:
    """HTTP client for the Open Brain server."""

    def __init__(
        self,
        url: str | None = None,
        *,
        timeout: int = 30,
        token: str | None = None,
    ) -> None:
        self.url = url or os.environ.get("OPEN_BRAIN_URL", DEFAULT_URL)
        parsed = urlparse(self.url)
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 11435
        self.timeout = timeout
        self.token = token or os.environ.get("OPEN_BRAIN_TOKEN")

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request and return parsed JSON."""
        conn = HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            data = None
            if body is not None:
                data = json.dumps(body, separators=(",", ":")).encode("utf-8")
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(data))

            conn.request(method, path, body=data, headers=headers)
            response = conn.getresponse()
            response_body = response.read(MAX_RESPONSE_SIZE).decode("utf-8")

            if response.status >= 400:
                try:
                    err = json.loads(response_body)
                    raise RuntimeError(
                        f"Open Brain error ({response.status}): {err.get('error', response_body)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(
                        f"Open Brain error ({response.status}): {response_body}"
                    )

            return json.loads(response_body)
        finally:
            conn.close()

    def search(
        self,
        query: str,
        *,
        token_budget: int = 2000,
        scope: str | None = None,
        entry_type: str | None = None,
        since: str | None = None,
        sources: list[str] | None = None,
        agent: str = "remote-client",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search the Open Brain."""
        params: dict[str, Any] = {
            "query": query,
            "token_budget": token_budget,
            "agent": agent,
            "limit": limit,
        }
        if scope:
            params["scope"] = scope
        if entry_type:
            params["entry_type"] = entry_type
        if since:
            params["since"] = since
        if sources:
            params["sources"] = sources

        response = self._request("POST", "/search", params)
        return response.get("results", [])

    def status(self) -> dict[str, Any]:
        """Get server status."""
        return self._request("GET", "/status")

    def health(self) -> bool:
        """Check if server is reachable."""
        try:
            resp = self._request("GET", "/health")
            return resp.get("status") == "ok"
        except (OSError, RuntimeError):
            return False

    def reindex(self) -> dict[str, Any]:
        """Trigger a reindex on the server."""
        return self._request("POST", "/reindex")

    def ingest(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Send entries from a local brain to the remote brain (federation)."""
        return self._request("POST", "/ingest", {"entries": entries})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open Brain Client -- query the remote knowledge compiler",
    )
    parser.add_argument(
        "--url", default=None,
        help=f"Server URL (default: OPEN_BRAIN_URL env or {DEFAULT_URL})",
    )

    subparsers = parser.add_subparsers(dest="command")

    p_search = subparsers.add_parser("search", help="Search the Open Brain")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--budget", type=int, default=2000)
    p_search.add_argument("--scope", help="Filter by scope")
    p_search.add_argument("--type", dest="entry_type", help="Filter by type")
    p_search.add_argument("--since", help="ISO timestamp filter")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--json", action="store_true", help="JSON output")

    subparsers.add_parser("status", help="Server status")
    subparsers.add_parser("reindex", help="Trigger reindex")
    subparsers.add_parser("health", help="Health check")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    client = OpenBrainClient(args.url)

    if args.command == "health":
        ok = client.health()
        print("OK" if ok else "UNREACHABLE")
        return 0 if ok else 1

    if args.command == "status":
        s = client.status()
        print(json.dumps(s, indent=2))
        return 0

    if args.command == "reindex":
        result = client.reindex()
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "search":
        results = client.search(
            args.query,
            token_budget=args.budget,
            scope=args.scope,
            entry_type=args.entry_type,
            since=args.since,
            limit=args.limit,
        )

        if not results:
            print("No results found.")
            return 0

        if args.json:
            for r in results:
                print(json.dumps(r, separators=(",", ":")))
        else:
            for i, r in enumerate(results, 1):
                source = r.get("source", "?")
                score = r.get("score", 0)
                content = r.get("content", "").replace("\n", " ")[:200]
                meta = r.get("metadata", {})
                ts = meta.get("timestamp", "")[:10] if meta.get("timestamp") else ""
                print(f"{i:2d}. [{source}] score={score:.3f} {ts}")
                print(f"    {content}")
                print()

        total_tokens = sum(r.get("tokens", 0) for r in results)
        print(f"--- {len(results)} results, ~{total_tokens} tokens ---")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
