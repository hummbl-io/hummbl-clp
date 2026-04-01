"""Research Queue Processor -- uses local LLM to process research questions.

Reads a research queue (JSON array of questions), uses a local LLM via Ollama
to generate findings for each, and ingests results into the Open Brain ledger.

Idempotent: tracks processed question hashes in a state file so re-runs skip
already-answered questions.

Dependencies: stdlib only. Ollama accessed via urllib.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hummbl_clp.core.models import LedgerEntry

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_STATE_FILE = "_state/cognition/research_processor_state.json"
DEFAULT_QUEUE_FILE = "_state/cognition/research_queue.json"
DEFAULT_OPEN_BRAIN_URL = "http://127.0.0.1:11435"

# Max questions to process per run
MAX_PER_RUN = 3
MAX_PREDICT = 1024


def _resolve_path(rel_path: str) -> Path:
    """Resolve a path relative to git root or cwd."""
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


def load_research_queue(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load the research queue from a JSON file.

    Returns an empty list if the file does not exist.
    """
    queue_path = _resolve_path(DEFAULT_QUEUE_FILE) if path is None else Path(path)

    if not queue_path.exists():
        logger.debug("Queue file %s not found", queue_path)
        return []

    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            logger.warning("Queue file %s is not a JSON array", queue_path)
            return []
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load queue file %s: %s", queue_path, exc)
        return []


def save_research_queue(
    queue: list[dict[str, Any]],
    path: str | Path | None = None,
) -> Path:
    """Write the research queue to a JSON file (crash-safe)."""
    queue_path = _resolve_path(DEFAULT_QUEUE_FILE) if path is None else Path(path)

    queue_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(queue_path.parent),
        prefix=".research_queue_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, str(queue_path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    return queue_path


def _question_hash(question: dict[str, Any]) -> str:
    """Hash a question for change detection."""
    h = hashlib.sha256()
    h.update(question["query"].encode("utf-8"))
    h.update(question.get("recurrence", "once").encode("utf-8"))
    return h.hexdigest()[:16]


def _load_state(state_file: Path) -> dict[str, Any]:
    """Load processor state."""
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"processed": {}, "last_run": None, "total_processed": 0}


def _save_state(state_file: Path, state: dict[str, Any]) -> None:
    """Save processor state."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state_file.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _is_kill_switch_engaged() -> bool:
    """Check if a kill switch is engaged."""
    return os.environ.get("CLP_KILL_SWITCH_ENGAGED", "").strip() in ("1", "true", "yes")


def _should_reprocess(
    question: dict[str, Any],
    processed: dict[str, Any],
) -> bool:
    """Determine if a question should be (re)processed."""
    qid = question["id"]
    entry = processed.get(qid)
    if not entry:
        return True

    current_hash = _question_hash(question)
    if entry.get("hash") != current_hash:
        return True

    recurrence = question.get("recurrence", "once")
    if recurrence == "once":
        return False

    last_processed = entry.get("last_processed")
    if not last_processed:
        return True

    try:
        last_dt = datetime.strptime(last_processed, "%Y-%m-%dT%H:%M:%SZ")
        last_dt = last_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_elapsed = (now - last_dt).days

        if recurrence == "weekly" and days_elapsed >= 7:
            return True
        if recurrence == "monthly" and days_elapsed >= 30:
            return True
    except (ValueError, TypeError):
        return True

    return False


def _ollama_research(
    question: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
    timeout_s: int = 180,
) -> str | None:
    """Use the local LLM to research a question."""
    prompt = f"""You are a research analyst for a multi-agent AI orchestration platform.
Answer the following research question with specific, actionable findings.
Structure your response as numbered findings (1-5 key points).
Each finding should be concrete and implementable, not abstract.
Domain: {question['domain']}

Research Question:
{question['query']}

Findings:"""

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.3,
            "num_predict": MAX_PREDICT,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url=f"{base_url}/api/generate",
        method="POST",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "")
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        logger.warning("Ollama research call failed for %s: %s", question["id"], e)
        return None


def _ingest_finding(
    question: dict[str, Any],
    findings: str,
    *,
    brain_url: str = DEFAULT_OPEN_BRAIN_URL,
) -> dict[str, Any]:
    """Ingest a research finding into the Open Brain server."""
    from http.client import HTTPConnection
    from urllib.parse import urlparse

    content = f"{question['id']}: {question['domain']}\n\n{findings.strip()}"
    if len(content) > 4000:
        content = content[:4000] + "\n[truncated]"

    entry = LedgerEntry.create(
        content=content,
        agent="research-processor",
        vendor="local",
        model=DEFAULT_MODEL,
        entry_type="discovery",
        scope="project",
        tags=[
            "research",
            f"domain:{question['domain']}",
            f"rq:{question['id'].lower()}",
            f"tier:{question.get('tier', 3)}",
        ],
        confidence=0.6,
    )

    parsed = urlparse(brain_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11435

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    token = os.environ.get("OPEN_BRAIN_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    conn = HTTPConnection(host, port, timeout=30)
    try:
        body = json.dumps(
            {"entries": [entry.to_dict()]}, separators=(",", ":"),
        ).encode("utf-8")
        headers["Content-Length"] = str(len(body))
        conn.request("POST", "/ingest", body=body, headers=headers)
        response = conn.getresponse()
        response_body = response.read().decode("utf-8")
        return json.loads(response_body)
    except Exception as e:
        return {"ingested": 0, "errors": [str(e)]}
    finally:
        conn.close()


def run_processor(
    *,
    queue: list[dict[str, Any]] | None = None,
    state_file: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    brain_url: str = DEFAULT_OPEN_BRAIN_URL,
    dry_run: bool = False,
    max_per_run: int = MAX_PER_RUN,
) -> dict[str, Any]:
    """Run one processor pass."""
    if _is_kill_switch_engaged():
        logger.warning("Kill switch engaged, skipping research")
        return {"processed": 0, "skipped": 0, "errors": ["kill switch engaged"],
                "questions": []}

    if queue is None:
        queue = load_research_queue()

    state_path = Path(state_file) if state_file else _resolve_path(DEFAULT_STATE_FILE)
    state = _load_state(state_path)
    processed_state = state.get("processed", {})

    sorted_queue = sorted(queue, key=lambda q: q.get("tier", 99))
    to_process = [
        q for q in sorted_queue
        if _should_reprocess(q, processed_state)
    ]
    to_process = to_process[:max_per_run]

    result: dict[str, Any] = {
        "processed": 0,
        "skipped": len(queue) - len(to_process),
        "errors": [],
        "questions": [q["id"] for q in to_process],
    }

    if not to_process:
        logger.info("No questions to process (all up to date)")
        _save_state(state_path, state)
        return result

    for question in to_process:
        if _is_kill_switch_engaged():
            result["errors"].append("kill switch engaged mid-run")
            break

        qid = question["id"]
        logger.info("Researching %s: %s", qid, question["domain"])

        if dry_run:
            logger.info("DRY RUN: Would research %s (%s)", qid, question["query"][:80])
            result["processed"] += 1
            continue

        findings = _ollama_research(question, model=model, base_url=ollama_url)
        if not findings:
            result["errors"].append(f"{qid}: Ollama call failed")
            continue

        logger.info("Got findings for %s (%d chars)", qid, len(findings))

        ingest_result = _ingest_finding(question, findings, brain_url=brain_url)
        if ingest_result.get("ingested", 0) > 0:
            result["processed"] += 1
            processed_state[qid] = {
                "hash": _question_hash(question),
                "last_processed": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "findings_length": len(findings),
            }
        else:
            errors = ingest_result.get("errors", [])
            result["errors"].append(f"{qid}: ingest failed: {errors}")

    state["processed"] = processed_state
    state["total_processed"] = state.get("total_processed", 0) + result["processed"]
    _save_state(state_path, state)

    return result


def processor_status(
    *,
    queue: list[dict[str, Any]] | None = None,
    state_file: str | Path | None = None,
) -> dict[str, Any]:
    """Report processor status."""
    if queue is None:
        queue = load_research_queue()
    state_path = Path(state_file) if state_file else _resolve_path(DEFAULT_STATE_FILE)
    state = _load_state(state_path)
    processed = state.get("processed", {})

    pending = [q["id"] for q in queue if _should_reprocess(q, processed)]
    completed = [q["id"] for q in queue if not _should_reprocess(q, processed)]

    return {
        "total_questions": len(queue),
        "pending": pending,
        "completed": completed,
        "total_processed": state.get("total_processed", 0),
        "last_run": state.get("last_run"),
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Research Queue Processor -- local LLM research for Open Brain",
    )
    parser.add_argument("--brain-url", default=DEFAULT_OPEN_BRAIN_URL)

    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run", help="Process research questions")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--model", default=DEFAULT_MODEL)
    p_run.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    p_run.add_argument("--state-file", help="Override state file")
    p_run.add_argument("--max", type=int, default=MAX_PER_RUN)

    p_status = subparsers.add_parser("status", help="Show processor status")
    p_status.add_argument("--state-file", help="Override state file")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    if args.command == "status":
        s = processor_status(state_file=getattr(args, "state_file", None))
        print(json.dumps(s, indent=2))
        return 0

    if args.command == "run":
        result = run_processor(
            state_file=args.state_file,
            model=args.model,
            ollama_url=args.ollama_url,
            brain_url=args.brain_url,
            dry_run=args.dry_run,
            max_per_run=args.max,
        )
        print(json.dumps(result, indent=2))
        return 0 if not result["errors"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
