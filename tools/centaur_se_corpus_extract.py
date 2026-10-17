#!/usr/bin/env python3
"""
Centaur-SE Corpus Pilot Extraction
Extracts git events from pilot repos for foundation model training.
"""

import subprocess
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional, List
import pandas as pd


PILOT_REPOS = [
    "hummbl-clp",
    "agents",
    "hummbl-bus",
    "hummbl-graphs",
    "hummbl-skills",
    "hummbl-intel",
    "hummbl-omnimeta",
    "hummbl-governance-intelligence",
    "hummbl-governance-kernel",
    "governance-as-code",
]

BASE_PATH = Path(r"C:\Users\Owner\PROJECTS")
OUTPUT_DIR = Path(r"C:\Users\Owner\AppData\Local\Temp\centaur-se-pilot")
DATE_START = "2025-01-01"
DATE_END = "2026-09-30"
SALT = "centaur-se-pilot-v1-20261009"


@dataclass
class GitEvent:
    event_id: str
    repo: str
    event_type: str  # commit, merge, tag
    timestamp_utc: str
    actor_hash: str
    actor_email: str
    commit_hash: str
    parent_hashes: List[str]
    message: str
    files_changed: int
    insertions: int
    deletions: int
    is_merge: bool
    branch: str
    diff_stats: dict


def hash_actor(email: str) -> str:
    """Pseudonymize contributor identity."""
    return hashlib.sha256(f"{SALT}:{email}".encode()).hexdigest()[:16]


def run_git(repo_path: Path, args: List[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path)] + args,
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def extract_commits(repo_name: str) -> List[GitEvent]:
    repo_path = BASE_PATH / repo_name
    if not repo_path.exists():
        print(f"  Repo not found: {repo_path}")
        return []

    # Get all commits in date range with full metadata
    fmt = "%H|%P|%an|%ae|%ci|%s|%b"
    log_output = run_git(repo_path, [
        "log", f"--since={DATE_START}", f"--until={DATE_END}",
        f"--pretty=format:{fmt}", "--all", "--reverse"
    ])

    if not log_output:
        return []

    events = []
    for line in log_output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 6)
        if len(parts) < 7:
            continue

        commit_hash, parents_str, author_name, author_email, timestamp, subject, body = parts
        parents = [p for p in parents_str.split(" ") if p]

        # Get diff stats
        stat_output = run_git(repo_path, ["show", "--stat", "--oneline", commit_hash])
        files_changed = 0
        insertions = 0
        deletions = 0
        for stat_line in stat_output.split("\n"):
            if "file" in stat_line and ("insertion" in stat_line or "deletion" in stat_line):
                # Parse: " 5 files changed, 123 insertions(+), 45 deletions(-)"
                import re
                m = re.search(r"(\d+) files? changed", stat_line)
                if m:
                    files_changed = int(m.group(1))
                m = re.search(r"(\d+) insertions?", stat_line)
                if m:
                    insertions = int(m.group(1))
                m = re.search(r"(\d+) deletions?", stat_line)
                if m:
                    deletions = int(m.group(1))

        # Get branch containing this commit
        branch_output = run_git(repo_path, ["branch", "-a", "--contains", commit_hash])
        branch = branch_output.split("\n")[0].strip().replace("* ", "") if branch_output else "unknown"

        # Determine event type
        is_merge = len(parents) > 1
        event_type = "merge" if is_merge else "commit"

        # Check if it's a tag
        tag_output = run_git(repo_path, ["tag", "--points-at", commit_hash])
        if tag_output:
            event_type = "tag"

        # Build event
        event_id = hashlib.sha256(f"{repo_name}:{commit_hash}".encode()).hexdigest()[:24]
        message = f"{subject}\n\n{body}".strip() if body.strip() else subject

        # Get diff summary for key files
        diff_output = run_git(repo_path, ["show", "--name-only", "--oneline", commit_hash])
        changed_files = [f.strip() for f in diff_output.split("\n")[1:] if f.strip() and not f.startswith("commit")]

        diff_stats = {
            "files": changed_files[:50],  # Limit
            "file_count": len(changed_files)
        }

        event = GitEvent(
            event_id=event_id,
            repo=repo_name,
            event_type=event_type,
            timestamp_utc=timestamp,
            actor_hash=hash_actor(author_email),
            actor_email=author_email,  # Keep for debugging, will drop in production
            commit_hash=commit_hash,
            parent_hashes=parents,
            message=message,
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
            is_merge=is_merge,
            branch=branch,
            diff_stats=diff_stats
        )
        events.append(event)

    return events


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_events = []
    repo_stats = {}

    for repo_name in PILOT_REPOS:
        print(f"Extracting {repo_name}...")
        events = extract_commits(repo_name)
        all_events.extend(events)
        repo_stats[repo_name] = len(events)
        print(f"  Extracted {len(events)} events")

    print(f"\nTotal events: {len(all_events)}")

    # Convert to DataFrame
    df = pd.DataFrame([asdict(e) for e in all_events])

    # Drop raw email for privacy (keep hash only)
    df = df.drop(columns=["actor_email"])

    # Sort by timestamp
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.sort_values("timestamp_utc").reset_index(drop=True)

    # Save as Parquet
    output_file = OUTPUT_DIR / "events.parquet"
    df.to_parquet(output_file, index=False, compression="snappy")
    print(f"Saved to {output_file}")

    # Save metadata
    meta = {
        "extraction_date": datetime.now(timezone.utc).isoformat(),
        "date_range": f"{DATE_START} to {DATE_END}",
        "repos": PILOT_REPOS,
        "repo_stats": repo_stats,
        "total_events": len(all_events),
        "schema_version": "1.0",
        "salt": SALT,
    }
    meta_file = OUTPUT_DIR / "metadata.json"
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata saved to {meta_file}")

    # Validation report
    print("\n=== VALIDATION REPORT ===")
    print(f"Event count: {len(df)}")
    print(f"Repos covered: {df['repo'].nunique()}")
    print(f"Date range: {df['timestamp_utc'].min()} to {df['timestamp_utc'].max()}")
    print(f"Event types: {df['event_type'].value_counts().to_dict()}")
    print(f"Unique actors: {df['actor_hash'].nunique()}")
    print(f"Merge commits: {df['is_merge'].sum()}")
    print(f"Avg files/commit: {df['files_changed'].mean():.1f}")

    # Check temporal gaps
    df_sorted = df.sort_values("timestamp_utc")
    gaps = df_sorted["timestamp_utc"].diff().dt.total_seconds()
    max_gap_days = gaps.max() / 86400
    print(f"Max temporal gap: {max_gap_days:.1f} days")

    # Per-repo breakdown
    print("\nPer-repo:")
    for repo, count in repo_stats.items():
        repo_df = df[df["repo"] == repo]
        print(f"  {repo}: {count} events, {repo_df['actor_hash'].nunique()} actors, "
              f"{repo_df['timestamp_utc'].min().date()} to {repo_df['timestamp_utc'].max().date()}")


if __name__ == "__main__":
    main()