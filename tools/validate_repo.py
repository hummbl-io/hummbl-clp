#!/usr/bin/env python3
"""Validate hummbl-clp repository baseline."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = (
    "README.md",
    "CLAUDE.md",
    "LICENSE",
    "pyproject.toml",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "src/hummbl_clp/core/__main__.py",
)
REQUIRED_DIRS = ("docs", "examples", "src", "tests", "tools")
REMOTE_PREFIXES = ("http://", "https://", "mailto:")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _iter_markdown() -> list[Path]:
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.md")
        if ".git" not in path.parts
    )


def _iter_python_sources() -> list[Path]:
    src_root = REPO_ROOT / "src"
    if not src_root.is_dir():
        return []
    return sorted(path for path in src_root.rglob("*.py"))


def _validate_required_surfaces() -> list[str]:
    failures: list[str] = []
    for rel_path in REQUIRED_FILES:
        path = REPO_ROOT / rel_path
        if not path.exists():
            failures.append(f"missing required file: {rel_path}")
        elif path.is_file() and not path.read_text(encoding="utf-8").strip():
            failures.append(f"required file is empty: {rel_path}")

    for rel_path in REQUIRED_DIRS:
        path = REPO_ROOT / rel_path
        if not path.is_dir():
            failures.append(f"missing required directory: {rel_path}")
    return failures


def _normalize_link_target(raw_target: str) -> str:
    target = raw_target.strip().split("#", 1)[0]
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return target


def _validate_markdown_links() -> list[str]:
    failures: list[str] = []
    for path in _iter_markdown():
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_RE.finditer(text):
            target = _normalize_link_target(match.group(1))
            if not target or target.startswith(REMOTE_PREFIXES):
                continue

            target_path = Path(target)
            if target_path.is_absolute():
                failures.append(f"{_relative(path)}: absolute local link {target!r}")
                continue

            resolved = (path.parent / target_path).resolve()
            try:
                resolved.relative_to(REPO_ROOT)
            except ValueError:
                failures.append(f"{_relative(path)}: link escapes repo {target!r}")
                continue
            if not resolved.exists():
                failures.append(f"{_relative(path)}: missing linked file {target!r}")
    return failures


def _validate_python_syntax() -> list[str]:
    failures: list[str] = []
    for path in _iter_python_sources():
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            failures.append(f"{_relative(path)}: {exc}")
    return failures


def main() -> int:
    failures = [
        *_validate_required_surfaces(),
        *_validate_markdown_links(),
        *_validate_python_syntax(),
    ]
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print("hummbl-clp repository validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
