"""Open Brain Consolidator -- groups related ledger entries and synthesizes summaries.

Runs periodically to compress the cognitive ledger without losing information.
Groups semantically related entries using BM25 similarity, then synthesizes
consolidated summaries via a local LLM (e.g., qwen3.5:9b on Ollama).

The consolidator is append-only: original entries are never modified.
Consolidated entries are new ledger entries of type "convention" with
`tags: ["consolidated"]` and `links` pointing to the source entries.

Safety:
    - Append-only: never modifies or deletes existing entries
    - Idempotent: skips entries already consolidated
    - Graceful degradation: works without Ollama (grouping only, no synthesis)

Dependencies: stdlib only. Ollama accessed via urllib.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hummbl_clp.core.indexer import tokenize
from hummbl_clp.core.ledger_writer import post_entry, read_entries
from hummbl_clp.core.models import LedgerEntry

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:9b"
MIN_GROUP_SIZE = 2
MAX_GROUP_SIZE = 10
SIMILARITY_THRESHOLD = 0.13
MAX_CONSOLIDATIONS_PER_RUN = 20


def _ollama_generate(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
    timeout_s: int = 120,
) -> str | None:
    """Call Ollama generate endpoint. Returns None on failure."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 512,
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
        logger.warning("Ollama call failed: %s", e)
        return None


def _is_kill_switch_engaged() -> bool:
    """Check if a kill switch is engaged (pluggable safety gate).

    Override this function or set CLP_KILL_SWITCH_ENGAGED=1 env var
    for host-specific kill switch integration.
    """
    import os
    return os.environ.get("CLP_KILL_SWITCH_ENGAGED", "").strip() in ("1", "true", "yes")


def _get_consolidated_ids(
    entries: list[LedgerEntry],
) -> set[str]:
    """Return IDs of entries that are already consolidated."""
    consolidated = set()
    for e in entries:
        if "consolidated" in e.tags and e.links:
            consolidated.update(e.links)
    return consolidated


def _compute_pairwise_similarity(
    entries: list[LedgerEntry],
) -> dict[str, dict[str, float]]:
    """Compute term overlap similarity between entry pairs."""
    doc_tokens: dict[str, set[str]] = {}
    for entry in entries:
        tokens = set(tokenize(entry.content))
        if tokens:
            doc_tokens[entry.id] = tokens

    similarity: dict[str, dict[str, float]] = defaultdict(dict)
    ids = list(doc_tokens.keys())

    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1:]:
            tokens_a = doc_tokens[id_a]
            tokens_b = doc_tokens[id_b]
            intersection = len(tokens_a & tokens_b)
            union = len(tokens_a | tokens_b)
            if union > 0:
                sim = intersection / union
                if sim >= SIMILARITY_THRESHOLD:
                    similarity[id_a][id_b] = sim
                    similarity[id_b][id_a] = sim

    return similarity


def _group_by_links(entries: list[LedgerEntry]) -> list[list[LedgerEntry]]:
    """Group entries into episodes by their Zettelkasten-style links."""
    entry_map = {e.id: e for e in entries}
    entry_ids = set(entry_map.keys())

    adjacency: dict[str, set[str]] = {eid: set() for eid in entry_ids}
    for entry in entries:
        for link_id in entry.links:
            if link_id in entry_ids:
                adjacency[entry.id].add(link_id)
                adjacency[link_id].add(entry.id)

    visited: set[str] = set()
    components: list[list[str]] = []
    for eid in entry_ids:
        if eid in visited:
            continue
        component: list[str] = []
        queue = [eid]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor in adjacency.get(current, ()):
                if neighbor not in visited:
                    queue.append(neighbor)
        if component:
            components.append(component)

    groups: list[list[LedgerEntry]] = []
    for comp in components:
        if len(comp) < MIN_GROUP_SIZE:
            continue
        group = [entry_map[eid] for eid in comp[:MAX_GROUP_SIZE]]
        groups.append(group)

    return groups


def _group_similar(
    entries: list[LedgerEntry],
    similarity: dict[str, dict[str, float]],
) -> list[list[LedgerEntry]]:
    """Group entries by similarity using greedy clustering."""
    entry_map = {e.id: e for e in entries}
    assigned: set[str] = set()
    groups: list[list[LedgerEntry]] = []

    scored = [
        (eid, len(similarity.get(eid, {})))
        for eid in entry_map
        if eid in similarity
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    for eid, _ in scored:
        if eid in assigned:
            continue

        group = [entry_map[eid]]
        assigned.add(eid)

        neighbors = sorted(
            similarity.get(eid, {}).items(),
            key=lambda x: x[1],
            reverse=True,
        )
        for neighbor_id, _ in neighbors:
            if neighbor_id in assigned:
                continue
            if len(group) >= MAX_GROUP_SIZE:
                break
            group.append(entry_map[neighbor_id])
            assigned.add(neighbor_id)

        if len(group) >= MIN_GROUP_SIZE:
            groups.append(group)

    return groups


def _synthesize_group(
    group: list[LedgerEntry],
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
) -> str | None:
    """Synthesize a consolidated summary for a group of related entries."""
    entries_text = "\n".join(
        f"- [{e.type}] ({e.agent}, {e.timestamp[:10]}): {e.content}"
        for e in group
    )

    prompt = f"""You are a knowledge consolidator for a multi-agent AI system.
Below are {len(group)} related memory entries. Synthesize them into a single
concise summary that captures the key insight. Keep it under 200 words.
Output ONLY the consolidated summary, no preamble.

Entries:
{entries_text}

Consolidated summary:"""

    return _ollama_generate(prompt, model=model, base_url=base_url)


def run_consolidation(
    *,
    ledger_path: str | Path | None = None,
    dry_run: bool = False,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
) -> dict[str, Any]:
    """Run one consolidation pass.

    Returns dict with: groups_found, consolidated, skipped, errors.
    """
    if _is_kill_switch_engaged():
        logger.warning("Kill switch engaged, skipping consolidation")
        return {"groups_found": 0, "consolidated": 0, "skipped": 0,
                "errors": ["kill switch engaged"]}

    entries = read_entries(ledger_path=ledger_path, limit=999_999)
    if not entries:
        return {"groups_found": 0, "consolidated": 0, "skipped": 0, "errors": []}

    already_consolidated = _get_consolidated_ids(entries)

    candidates = [
        e for e in entries
        if e.id not in already_consolidated and "consolidated" not in e.tags
    ]

    if len(candidates) < MIN_GROUP_SIZE:
        return {"groups_found": 0, "consolidated": 0, "skipped": 0, "errors": []}

    link_groups = _group_by_links(candidates)

    linked_ids = {e.id for g in link_groups for e in g}
    unlinked = [e for e in candidates if e.id not in linked_ids]
    similarity = _compute_pairwise_similarity(unlinked)
    sim_groups = _group_similar(unlinked, similarity)

    groups = link_groups + sim_groups
    groups = groups[:MAX_CONSOLIDATIONS_PER_RUN]

    result = {
        "groups_found": len(groups),
        "consolidated": 0,
        "skipped": 0,
        "errors": [],
    }

    for group in groups:
        if _is_kill_switch_engaged():
            result["errors"].append("kill switch engaged mid-run")
            break

        source_ids = tuple(e.id for e in group)

        if dry_run:
            logger.info(
                "DRY RUN: Would consolidate %d entries: %s",
                len(group),
                [e.content[:60] for e in group],
            )
            result["consolidated"] += 1
            continue

        summary = _synthesize_group(group, model=model, base_url=base_url)
        if not summary:
            summary = "Consolidated from related entries:\n" + "\n".join(
                f"- {e.content[:150]}" for e in group
            )
            logger.info("Using fallback consolidation (Ollama unavailable)")

        try:
            consolidated_entry = LedgerEntry.create(
                content=summary.strip(),
                agent="consolidator",
                vendor="local",
                model=model,
                entry_type="convention",
                scope="project",
                tags=["consolidated", f"group-size-{len(group)}"],
                links=source_ids,
            )
            post_entry(consolidated_entry, ledger_path=ledger_path)
            result["consolidated"] += 1
            logger.info(
                "Consolidated %d entries -> %s",
                len(group),
                consolidated_entry.id,
            )
        except (ValueError, OSError) as e:
            result["errors"].append(str(e))

    return result


def status(*, ledger_path: str | Path | None = None) -> dict[str, Any]:
    """Report consolidation status."""
    entries = read_entries(ledger_path=ledger_path, limit=999_999)
    consolidated_entries = [e for e in entries if "consolidated" in e.tags]
    consolidated_ids = _get_consolidated_ids(entries)

    return {
        "total_entries": len(entries),
        "consolidated_entries": len(consolidated_entries),
        "source_entries_covered": len(consolidated_ids),
        "unconsolidated": len(entries) - len(consolidated_entries) - len(consolidated_ids),
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Open Brain Consolidator -- group and synthesize related memories",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run", help="Run consolidation pass")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--model", default=DEFAULT_MODEL)
    p_run.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    p_run.add_argument("--ledger", help="Override ledger path")

    p_status = subparsers.add_parser("status", help="Show consolidation status")
    p_status.add_argument("--ledger", help="Override ledger path")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    if args.command == "status":
        s = status(ledger_path=getattr(args, "ledger", None))
        print(json.dumps(s, indent=2))
        return 0

    if args.command == "run":
        result = run_consolidation(
            ledger_path=args.ledger,
            dry_run=args.dry_run,
            model=args.model,
            base_url=args.ollama_url,
        )
        print(json.dumps(result, indent=2))
        return 0 if not result["errors"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
