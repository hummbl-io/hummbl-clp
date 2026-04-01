"""CLI entry point for the Cognitive Ledger.

Usage:
    python -m hummbl_clp.core <command> [options]
    hummbl-clp <command> [options]

Commands:
    post      Write a new ledger entry
    post-verified  Write a verified ledger entry with evidence + confidence
    query     Query ledger with filters
    validate  Validate ledger integrity
    state     Show current shared state
    boot      Generate boot context for agent injection
    reindex   Rebuild the search index from ledger
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hummbl_clp.core.ledger_writer import (
    post_entry,
    read_entries,
    validate_integrity,
)
from hummbl_clp.core.models import (
    VALID_VENDORS,
    LedgerEntry,
    LedgerEntryType,
    LedgerScope,
    SharedState,
)
from hummbl_clp.core.verified_writer import post_verified_entry


def cmd_post(args: argparse.Namespace) -> int:
    """Post a new ledger entry."""
    try:
        entry = LedgerEntry.create(
            agent=args.agent,
            vendor=args.vendor,
            model=args.model,
            entry_type=args.type,
            scope=args.scope,
            content=args.content,
            evidence=args.evidence,
            confidence=args.confidence,
            supersedes=args.supersedes,
            tags=tuple(args.tags) if args.tags else (),
            assurance_level=args.assurance_level,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        written = post_entry(entry, ledger_path=args.ledger)
    except (ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Posted: {written.id} ({written.type}/{written.scope})")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Query ledger entries."""
    entries = read_entries(
        ledger_path=args.ledger,
        since=args.since,
        entry_type=args.type,
        scope=args.scope,
        agent=args.agent,
        tags=args.tags,
        limit=args.limit,
    )

    if not entries:
        print("No entries found.")
        return 0

    if args.json:
        for entry in entries:
            print(entry.to_jsonl())
    else:
        for entry in entries:
            tags_str = f" [{', '.join(entry.tags)}]" if entry.tags else ""
            sup_str = f" (supersedes {entry.supersedes})" if entry.supersedes else ""
            print(
                f"[{entry.timestamp}] ({entry.agent}) "
                f"{entry.type.upper()}/{entry.scope}: "
                f"{entry.content[:120]}"
                f"{tags_str}{sup_str}"
            )

    print(f"\n--- {len(entries)} entries ---")
    return 0


def cmd_post_verified(args: argparse.Namespace) -> int:
    """Post a verified ledger entry with required evidence and confidence."""
    try:
        written = post_verified_entry(
            agent=args.agent,
            vendor=args.vendor,
            model=args.model,
            entry_type=args.type,
            scope=args.scope,
            content=args.content,
            evidence=args.evidence,
            confidence=args.confidence,
            supersedes=args.supersedes,
            tags=tuple(args.tags) if args.tags else (),
            assurance_level=args.assurance_level,
            ledger_path=args.ledger,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"Posted verified: {written.id} "
        f"({written.type}/{written.scope}) evidence={written.evidence}"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate ledger integrity."""
    valid, errors = validate_integrity(ledger_path=args.ledger)

    if errors:
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        print(f"\nValidation: {valid} valid, {len(errors)} errors")
        return 1

    print(f"Validation: {valid} entries, all OK")
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    """Show current shared state."""
    state_path = args.state
    if state_path is None:
        ledger_path = args.ledger or "_state/cognition/ledger.jsonl"
        state_path = str(Path(ledger_path).parent / "state.json")

    path = Path(state_path)
    if not path.exists():
        print("No shared state file found.")
        print(f"Expected at: {path}")
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        state = SharedState.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"ERROR: failed to parse state: {e}", file=sys.stderr)
        return 1

    print(f"Version: {state.version}")
    print(f"Updated: {state.updated_at} by {state.updated_by}")

    if state.active_agents:
        print(f"\nActive Agents ({len(state.active_agents)}):")
        for agent_id, info in state.active_agents.items():
            status = info.get("status", "unknown")
            print(f"  {agent_id}: {status}")

    if state.claimed_files:
        print(f"\nClaimed Files ({len(state.claimed_files)}):")
        for filepath, info in state.claimed_files.items():
            agent = info.get("agent", "unknown")
            print(f"  {filepath} -> {agent}")

    if state.sprint:
        print(f"\nSprint: {state.sprint.get('name', 'unnamed')}")

    if state.flags:
        print(f"\nFlags: {json.dumps(state.flags)}")

    return 0


def cmd_boot(args: argparse.Namespace) -> int:
    """Generate boot context for agent injection."""
    from hummbl_clp.extensions.boot_context import build_boot_context

    cognition_dir = Path(args.ledger).parent if args.ledger else None
    print(
        build_boot_context(
            cognition_dir=cognition_dir,
            max_entries=args.max_entries,
            max_age_days=args.max_age_days,
        )
    )
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    """Rebuild the search index."""
    from hummbl_clp.core.indexer import BM25Index

    index = BM25Index()
    count = index.build(ledger_path=args.ledger)
    path = index.save()
    print(f"Indexed {count} entries -> {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="hummbl-clp",
        description="Cognitive Ledger Protocol -- vendor-agnostic shared agent memory",
    )
    parser.add_argument(
        "--ledger",
        help="Override ledger file path",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # post
    p_post = subparsers.add_parser("post", help="Write a new ledger entry")
    p_post.add_argument("--agent", required=True, help="Agent identifier")
    p_post.add_argument(
        "--vendor",
        required=True,
        choices=sorted(VALID_VENDORS),
        help="Vendor identifier",
    )
    p_post.add_argument("--model", required=True, help="Model identifier")
    p_post.add_argument(
        "--type",
        required=True,
        choices=[e.value for e in LedgerEntryType],
        help="Entry type",
    )
    p_post.add_argument(
        "--scope",
        required=True,
        choices=[e.value for e in LedgerScope],
        help="Entry scope",
    )
    p_post.add_argument("--content", required=True, help="Knowledge content")
    p_post.add_argument("--evidence", help="Link to supporting artifact")
    p_post.add_argument(
        "--confidence", type=float, default=0.9, help="Confidence 0.0-1.0"
    )
    p_post.add_argument("--supersedes", help="ID of entry to correct")
    p_post.add_argument("--tags", nargs="*", default=[], help="Tags")
    p_post.add_argument(
        "--assurance-level",
        choices=["SELF", "PEER", "VERIFIED"],
        help="Trust level",
    )

    # query
    p_query = subparsers.add_parser("query", help="Query ledger entries")
    p_query.add_argument("--since", help="ISO 8601 timestamp filter")
    p_query.add_argument(
        "--type",
        choices=[e.value for e in LedgerEntryType],
        help="Filter by type",
    )
    p_query.add_argument(
        "--scope",
        choices=[e.value for e in LedgerScope],
        help="Filter by scope",
    )
    p_query.add_argument("--agent", help="Filter by agent (substring)")
    p_query.add_argument("--tags", nargs="*", help="Filter by tags (all must match)")
    p_query.add_argument("--limit", type=int, default=20, help="Max entries")
    p_query.add_argument("--json", action="store_true", help="Output as JSONL")

    # post-verified
    p_post_verified = subparsers.add_parser(
        "post-verified",
        help="Write a verified ledger entry with evidence + confidence",
    )
    p_post_verified.add_argument("--agent", help="Agent identifier or COGNITION_AGENT")
    p_post_verified.add_argument(
        "--vendor",
        choices=sorted(VALID_VENDORS),
        help="Vendor identifier or COGNITION_VENDOR",
    )
    p_post_verified.add_argument(
        "--model",
        help="Model identifier or COGNITION_MODEL",
    )
    p_post_verified.add_argument(
        "--type",
        required=True,
        choices=[e.value for e in LedgerEntryType],
        help="Entry type",
    )
    p_post_verified.add_argument(
        "--scope",
        required=True,
        choices=[e.value for e in LedgerScope],
        help="Entry scope",
    )
    p_post_verified.add_argument("--content", required=True, help="Knowledge content")
    p_post_verified.add_argument(
        "--evidence",
        required=True,
        help="Supporting artifact or verification receipt",
    )
    p_post_verified.add_argument(
        "--confidence",
        required=True,
        type=float,
        help="Explicit confidence 0.0-1.0",
    )
    p_post_verified.add_argument("--supersedes", help="ID of entry to correct")
    p_post_verified.add_argument("--tags", nargs="*", default=[], help="Tags")
    p_post_verified.add_argument(
        "--assurance-level",
        choices=["SELF", "PEER", "VERIFIED"],
        help="Trust level",
    )

    # reindex
    subparsers.add_parser("reindex", help="Rebuild the search index")

    # validate
    subparsers.add_parser("validate", help="Validate ledger integrity")

    # state
    p_state = subparsers.add_parser("state", help="Show shared state")
    p_state.add_argument("--state", help="Override state.json path")

    # boot
    p_boot = subparsers.add_parser("boot", help="Generate boot context")
    p_boot.add_argument(
        "--boot-limit",
        "--max-entries",
        dest="max_entries",
        type=int,
        default=20,
        help="Max ledger entries in boot context",
    )
    p_boot.add_argument(
        "--max-age-days",
        type=int,
        default=14,
        help="Only include ledger entries newer than this many days",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    handlers = {
        "post": cmd_post,
        "post-verified": cmd_post_verified,
        "query": cmd_query,
        "reindex": cmd_reindex,
        "validate": cmd_validate,
        "state": cmd_state,
        "boot": cmd_boot,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
