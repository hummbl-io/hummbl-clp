#!/usr/bin/env python3
"""
Centaur-SE Corpus Pilot Extraction - Debug Version
"""

import subprocess
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List
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
    event_type: str
    timestamp_utc: str
    actor_hash: str
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
    return hashlib.sha256(f"{SALT}:{email}".encode()).hexdigest()[:16]


def run_git(repo_path: Path, args: List[str]) -> str:
    print(f"  git {' '.join(args)}")
    result = subprocess.run(
        ["git", "-C", str(repo_path)] + args,
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
    return result.stdout.strip()


def extract_commits(repo_name: str) -> List[GitEvent]:
    repo_path = BASE_PATH / repo_name
    if not repo_path.exists():
        print(f"  Repo not found: {repo_path}")
        return []

    print(f"  Running git log...")
    fmt = "%H|%P|%an|%ae|%ci|%s|%b"
    log_output = run_git(repo_path, [
        "log", f"--since={DATE_START}", f"--until={DATE_END}",
        f"--pretty=format:{fmt}", "--all", "--reverse", "--numstat"
    ])

    print(f"  Got {len(log_output)} chars")

    if not log_output:
        return []

    print(f"  Fetching tags...")
    tag_output = run_git(repo_path, ["tag", "--format=%(refname:short)|%(objectname)"])
    tag_map = {}
    for line in tag_output.split("\n"):
        if "|" in line:
            tag_name, obj_hash = line.split("|", 1)
            tag_map[obj_hash] = tag_name

    print(f"  Fetching branches...")
    branch_output = run_git(repo_path, ["for-each-ref", "--format=%(objectname)|%(refname:short)", "refs/heads/", "refs/remotes/"])
    branch_map = {}
    for line in branch_output.split("\n"):
        if "|" in line:
            obj_hash, branch_name = line.split("|", 1)
            if obj_hash not in branch_map:
                branch_map[obj_hash] = []
            branch_map[obj_hash].append(branch_name)

    print(f"  Parsing {len(log_output.split(chr(10)))} lines...")
    events = []
    current = None
    files_changed = 0
    insertions = 0
    deletions = 0
    changed_files = []

    for i, line in enumerate(log_output.split("\n")):
        if i % 100 == 0:
            print(f"    Line {i}/{len(log_output.split(chr(10)))}")

        if not line.strip():
            continue

        if "|" in line and line.count("|") >= 6:
            if current:
                commit_hash = current['hash']
                event_type = "tag" if commit_hash in tag_map else ("merge" if current['is_merge'] else "commit")
                branch = branch_map.get(commit_hash, ["unknown"])[0] if commit_hash in branch_map else "unknown"

                events.append(GitEvent(
                    event_id=hashlib.sha256(f"{repo_name}:{commit_hash}".encode()).hexdigest()[:24],
                    repo=repo_name,
                    event_type=event_type,
                    timestamp_utc=current['timestamp'],
                    actor_hash=hash_actor(current['email']),
                    commit_hash=commit_hash,
                    parent_hashes=current['parents'],
                    message=current['message'],
                    files_changed=files_changed,
                    insertions=insertions,
                    deletions=deletions,
                    is_merge=current['is_merge'],
                    branch=branch,
                    diff_stats={"files": changed_files[:50], "file_count": len(changed_files)}
                ))

            parts = line.split("|", 6)
            commit_hash, parents_str, author_name, author_email, timestamp, subject, body = parts
            parents = [p for p in parents_str.split(" ") if p]
            is_merge = len(parents) > 1
            message = f"{subject}\n\n{body}".strip() if body.strip() else subject

            current = {
                'hash': commit_hash,
                'parents': parents,
                'email': author_email,
                'timestamp': timestamp,
                'is_merge': is_merge,
                'message': message
            }

            files_changed = 0
            insertions = 0
            deletions = 0
            changed_files = []

        else:
            parts = line.split("\t")
            if len(parts) == 3:
                try:
                    ins = int(parts[0]) if parts[0] != "-" else 0
                    dels = int(parts[1]) if parts[1] != "-" else 0
                    fname = parts[2]
                    insertions += ins
                    deletions += dels
                    files_changed += 1
                    changed_files.append(fname)
                except ValueError:
                    pass

    if current:
        commit_hash = current['hash']
        event_type = "tag" if commit_hash in tag_map else ("merge" if current['is_merge'] else "commit")
        branch = branch_map.get(commit_hash, ["unknown"])[0] if commit_hash in branch_map else "unknown"

        events.append(GitEvent(
            event_id=hashlib.sha256(f"{repo_name}:{commit_hash}".encode()).hexdigest()[:24],
            repo=repo_name,
            event_type=event_type,
            timestamp_utc=current['timestamp'],
            actor_hash=hash_actor(current['email']),
            commit_hash=commit_hash,
            parent_hashes=current['parents'],
            message=current['message'],
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
            is_merge=current['is_merge'],
            branch=branch,
            diff_stats={"files": changed_files[:50], "file_count": len(changed_files)}
        ))

    print(f"  Done: {len(events)} events")
    return events


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_events = []
    repo_stats = {}

    for repo_name in PILOT_REPOS:
        print(f"\n=== Extracting {repo_name} ===")
        events = extract_commits(repo_name)
        all_events.extend(events)
        repo_stats[repo_name] = len(events)
        print(f"  Extracted {len(events)} events")

    print(f"\nTotal events: {len(all_events)}")

    df = pd.DataFrame([asdict(e) for e in all_events])
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.sort_values("timestamp_utc").reset_index(drop=True)

    output_file = OUTPUT_DIR / "events.parquet"
    df.to_parquet(output_file, index=False, compression="snappy")
    print(f"Saved to {output_file}")

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

    print("\n=== VALIDATION REPORT ===")
    print(f"Event count: {len(df)}")
    print(f"Repos covered: {df['repo'].nunique()}")
    print(f"Date range: {df['timestamp_utc'].min()} to {df['timestamp_utc'].max()}")
    print(f"Event types: {df['event_type'].value_counts().to_dict()}")
    print(f"Unique actors: {df['actor_hash'].nunique()}")
    print(f"Merge commits: {df['is_merge'].sum()}")
    print(f"Avg files/commit: {df['files_changed'].mean():.1f}")

    gaps = df["timestamp_utc"].diff().dt.total_seconds()
    max_gap_days = gaps.max() / 86400
    print(f"Max temporal gap: {max_gap_days:.1f} days")

    print("\nPer-repo:")
    for repo, count in repo_stats.items():
        repo_df = df[df["repo"] == repo]
        print(f"  {repo}: {count} events, {repo_df['actor_hash'].nunique()} actors, "
              f"{repo_df['timestamp_utc'].min().date()} to {repo_df['timestamp_utc'].max().date()}")


if __name__ == "__main__":
    main()