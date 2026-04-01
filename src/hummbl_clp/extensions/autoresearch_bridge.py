"""Autoresearch Bridge -- ingests findings from autoresearch-reports into Open Brain.

Pulls a git repo of research reports, parses markdown reports and findings,
converts them to ledger entries, and ingests them into the Open Brain server.

Idempotent: tracks ingested files in a state file so re-runs skip already
processed reports.

Dependencies: stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REPO_URL = ""  # Set via env or CLI arg -- no hardcoded repo URL
DEFAULT_REPO_DIR = "_state/autoresearch-reports"
DEFAULT_STATE_FILE = "_state/cognition/autoresearch_bridge_state.json"
DEFAULT_OPEN_BRAIN_URL = "http://127.0.0.1:11435"

SCAN_DIRS = ["reports", "findings", "proposals"]
MAX_CONTENT_LENGTH = 2000


def _resolve_path(rel_path: str) -> Path:
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if root:
            return Path(root) / rel_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path(rel_path)


def _git_clone_or_pull(repo_url: str, repo_dir: Path) -> bool:
    """Clone or pull a repo. Returns True on success."""
    if not repo_url:
        logger.warning("No repo URL configured for autoresearch bridge")
        return False

    if (repo_dir / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(repo_dir),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning("git pull failed (rc=%d): %s", result.returncode, result.stderr)
                return False
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("git pull failed: %s", e)
            return False
    else:
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", repo_url, str(repo_dir)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                logger.warning("git clone failed (rc=%d): %s", result.returncode, result.stderr)
                return False
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("git clone failed: %s", e)
            return False


def _load_state(state_file: Path) -> dict[str, Any]:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"ingested_files": {}, "last_run": None}


def _save_state(state_file: Path, state: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state_file.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _extract_title(content: str) -> str:
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_summary(content: str) -> str:
    summary_match = re.search(
        r"##\s*Executive\s+Summary\s*\n+(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if summary_match:
        text = summary_match.group(1).strip()
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return "\n\n".join(paragraphs[:2])[:MAX_CONTENT_LENGTH]

    lines = content.split("\n")
    in_body = False
    paragraphs = []
    current = []
    for line in lines:
        if line.startswith("# ") and not in_body:
            in_body = True
            continue
        if in_body:
            if line.strip():
                current.append(line.strip())
            elif current:
                paragraphs.append(" ".join(current))
                current = []
                if len(paragraphs) >= 2:
                    break
    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs[:2])[:MAX_CONTENT_LENGTH]


def _classify_type(filepath: Path) -> str:
    parent = filepath.parent.name
    if parent == "findings":
        return "discovery"
    if parent == "proposals":
        return "lesson"
    return "discovery"


def _parse_report(filepath: Path) -> dict[str, Any] | None:
    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError:
        return None

    if not content.strip() or len(content.strip()) < 50:
        return None

    title = _extract_title(content)
    summary = _extract_summary(content)

    if not summary:
        summary = content[:MAX_CONTENT_LENGTH]

    entry_content = f"{title}\n\n{summary}" if title else summary

    date_match = re.match(r"(\d{4}-\d{2}-\d{2})", filepath.name)
    timestamp = None
    if date_match:
        timestamp = f"{date_match.group(1)}T00:00:00Z"

    tags = ["autoresearch", f"source:{filepath.parent.name}"]

    rq_match = re.search(r"RQ-(\d+)", content)
    if rq_match:
        tags.append(f"rq-{rq_match.group(1)}")

    return {
        "content": entry_content.strip(),
        "agent": "autoresearch-bridge",
        "vendor": "local",
        "model": "autoresearch",
        "type": _classify_type(filepath),
        "scope": "project",
        "tags": tags,
        "confidence": 0.7,
        **({"timestamp": timestamp} if timestamp else {}),
    }


def _ingest_to_open_brain(
    entries: list[dict[str, Any]],
    *,
    brain_url: str = DEFAULT_OPEN_BRAIN_URL,
) -> dict[str, Any]:
    from http.client import HTTPConnection
    from urllib.parse import urlparse

    parsed = urlparse(brain_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11435

    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = os.environ.get("OPEN_BRAIN_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    conn = HTTPConnection(host, port, timeout=30)
    try:
        body = json.dumps({"entries": entries}, separators=(",", ":")).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        conn.request("POST", "/ingest", body=body, headers=headers)
        response = conn.getresponse()
        response_body = response.read().decode("utf-8")
        return json.loads(response_body)
    except Exception as e:
        return {"ingested": 0, "errors": [str(e)]}
    finally:
        conn.close()


def run_bridge(
    *,
    repo_url: str = DEFAULT_REPO_URL,
    repo_dir: str | Path | None = None,
    state_file: str | Path | None = None,
    brain_url: str = DEFAULT_OPEN_BRAIN_URL,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one bridge pass."""
    repo_path = Path(repo_dir) if repo_dir else _resolve_path(DEFAULT_REPO_DIR)
    state_path = Path(state_file) if state_file else _resolve_path(DEFAULT_STATE_FILE)

    if not _git_clone_or_pull(repo_url, repo_path):
        return {"new_files": 0, "ingested": 0, "errors": ["git pull/clone failed"]}

    state = _load_state(state_path)
    ingested_files = state.get("ingested_files", {})

    new_entries: list[dict[str, Any]] = []
    new_file_hashes: dict[str, str] = {}

    for scan_dir in SCAN_DIRS:
        dir_path = repo_path / scan_dir
        if not dir_path.exists():
            continue

        for md_file in sorted(dir_path.glob("*.md")):
            if md_file.name.startswith("."):
                continue

            file_key = str(md_file.relative_to(repo_path))
            current_hash = _file_hash(md_file)

            if ingested_files.get(file_key) == current_hash:
                continue

            entry = _parse_report(md_file)
            if entry:
                new_entries.append(entry)
                new_file_hashes[file_key] = current_hash

    result: dict[str, Any] = {
        "new_files": len(new_entries),
        "ingested": 0,
        "errors": [],
        "files": list(new_file_hashes.keys()),
    }

    if not new_entries:
        _save_state(state_path, state)
        return result

    if dry_run:
        result["ingested"] = len(new_entries)
        return result

    ingest_result = _ingest_to_open_brain(new_entries, brain_url=brain_url)
    result["ingested"] = ingest_result.get("ingested", 0)
    result["errors"] = ingest_result.get("errors", [])

    if result["ingested"] > 0:
        ingested_files.update(new_file_hashes)
        state["ingested_files"] = ingested_files
        _save_state(state_path, state)

    return result


def bridge_status(
    *,
    state_file: str | Path | None = None,
    brain_url: str = DEFAULT_OPEN_BRAIN_URL,
) -> dict[str, Any]:
    state_path = Path(state_file) if state_file else _resolve_path(DEFAULT_STATE_FILE)
    state = _load_state(state_path)

    brain_ok = False
    try:
        from http.client import HTTPConnection
        from urllib.parse import urlparse

        parsed = urlparse(brain_url)
        conn = HTTPConnection(parsed.hostname or "127.0.0.1", parsed.port or 11435, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        brain_ok = resp.status == 200
        conn.close()
    except Exception:
        pass

    return {
        "last_run": state.get("last_run"),
        "ingested_files_count": len(state.get("ingested_files", {})),
        "ingested_files": list(state.get("ingested_files", {}).keys()),
        "open_brain_reachable": brain_ok,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Autoresearch Bridge -- ingest findings into Open Brain",
    )
    parser.add_argument("--brain-url", default=DEFAULT_OPEN_BRAIN_URL)
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="Git repo URL")

    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run", help="Run bridge pass")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--repo-dir", help="Override repo directory")
    p_run.add_argument("--state-file", help="Override state file")

    p_status = subparsers.add_parser("status", help="Show bridge status")
    p_status.add_argument("--state-file", help="Override state file")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    if args.command == "status":
        s = bridge_status(
            state_file=getattr(args, "state_file", None),
            brain_url=args.brain_url,
        )
        print(json.dumps(s, indent=2))
        return 0

    if args.command == "run":
        result = run_bridge(
            repo_url=args.repo_url,
            repo_dir=getattr(args, "repo_dir", None),
            state_file=getattr(args, "state_file", None),
            brain_url=args.brain_url,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0 if not result["errors"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
