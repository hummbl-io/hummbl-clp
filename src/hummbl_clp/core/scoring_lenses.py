"""Scoring Lenses -- swappable analytical prompts for experiment data.

Inspired by Karpathy's jobs tool pattern: same pipeline, different analytical
lens via prompt swap. Reads experiment data (results.tsv from MLX dialectic
analysis) and applies a configurable "lens" (a named prompt template) to
score/analyze the data through Ollama, producing structured findings compatible
with research_digest.

Usage:
    python -m hummbl_clp.core.scoring_lenses --lens convergence --data results.tsv
    python -m hummbl_clp.core.scoring_lenses --lens risk --data results.tsv --dry-run
    python -m hummbl_clp.core.scoring_lenses list

Zero third-party dependencies (stdlib only). Ollama accessed via urllib.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = "qwen3.5:9b"
MAX_PREDICT = 2048


# ---------------------------------------------------------------------------
# ScoringLens dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoringLens:
    """A named analytical lens with a prompt template for scoring experiment data.

    Each lens defines a system prompt that frames how experiment data should be
    analyzed, a temperature for LLM generation, and the expected output format.
    """

    name: str
    description: str
    system_prompt: str
    temperature: float = 0.3
    output_format: str = "findings_json"
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Lens name must be alphanumeric (hyphens/underscores allowed): {self.name!r}"
            )
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                f"Temperature must be 0.0-2.0, got {self.temperature}"
            )
        if not self.system_prompt:
            raise ValueError("system_prompt cannot be empty")


# ---------------------------------------------------------------------------
# Finding schema (compatible with research_digest)
# ---------------------------------------------------------------------------

FINDING_SCHEMA_DESCRIPTION = """\
Each finding must be a JSON object with these fields:
  - "id": string, a short identifier like "F-001"
  - "claim": string, a specific factual claim (max 200 chars)
  - "confidence": float 0.0-1.0, how confident you are in this claim
  - "actionable": boolean, whether this finding suggests a concrete action
  - "target": string, which system/config/component this applies to
  - "effort": string, one of "low", "medium", "high"
  - "category": string, the lens category that produced this finding
"""

# The user prompt template. {lens_name}, {data_summary}, {column_info} are
# injected at runtime.
USER_PROMPT_TEMPLATE = """\
Analyze the following experiment data through the {lens_name} lens.

Column schema: {column_info}

Data:
{data_summary}

Produce exactly 3-5 findings as a JSON array. Each finding must follow this schema:
{schema}

Return ONLY the JSON array, no markdown fences, no commentary."""


# ---------------------------------------------------------------------------
# Built-in lenses
# ---------------------------------------------------------------------------

CONVERGENCE_LENS = ScoringLens(
    name="convergence",
    description="Analyze convergence patterns and plateau detection in training runs",
    system_prompt=(
        "You are a machine learning convergence analyst. Your job is to examine "
        "training experiment results and identify convergence patterns: which "
        "configurations converge fastest, which plateau early, which show "
        "instability or oscillation, and which achieve the best final loss. "
        "Focus on bits-per-byte (val_bpb) trends across commits. Flag runs that "
        "appear stuck in local minima or that show diminishing returns. "
        "Be quantitative -- cite specific values and deltas."
    ),
    temperature=0.2,
    tags=("mlx", "training", "convergence"),
)

EFFICIENCY_LENS = ScoringLens(
    name="efficiency",
    description="Analyze compute/memory efficiency trade-offs across configurations",
    system_prompt=(
        "You are a compute efficiency analyst for ML training experiments. "
        "Your job is to evaluate the trade-off between model quality (val_bpb) "
        "and resource usage (memory_gb). Identify configurations that achieve "
        "the best quality-per-GB ratio. Flag wasteful configs where memory "
        "increases yield negligible quality gains. Identify the Pareto frontier "
        "of efficiency. Consider whether smaller, faster configurations might "
        "be preferable for iteration speed. Be specific about ratios and "
        "cost-effectiveness."
    ),
    temperature=0.3,
    tags=("mlx", "efficiency", "memory"),
)

RISK_LENS = ScoringLens(
    name="risk",
    description="Identify fragile configs, high-variance results, and overfitting signals",
    system_prompt=(
        "You are a risk analyst for ML experiments. Your job is to identify "
        "fragile or risky configurations: runs that failed (status != pass), "
        "configs with unusually high memory that might OOM on smaller hardware, "
        "results that look suspiciously good (possible overfitting), configs "
        "near hardware limits, and any patterns suggesting instability. "
        "Flag high-variance results where small config changes cause large "
        "quality swings. Assess which configurations are safe for production "
        "vs experimental-only. Be conservative -- when in doubt, flag it."
    ),
    temperature=0.4,
    tags=("mlx", "risk", "stability"),
)

TRANSFER_LENS = ScoringLens(
    name="transfer",
    description="Assess which findings transfer across hardware (RTX vs MLX)",
    system_prompt=(
        "You are a hardware portability analyst for ML experiments. Your job "
        "is to assess which experimental findings are likely to transfer across "
        "different hardware backends (Apple MLX vs NVIDIA RTX). Consider: "
        "memory scaling patterns (unified vs discrete memory), numerical "
        "precision differences, batch size implications, and which "
        "hyperparameter choices are hardware-specific vs universal. "
        "Identify findings that are architecture-dependent and should be "
        "re-validated on other hardware. Flag configs that exploit "
        "hardware-specific features (e.g., unified memory) and may not port."
    ),
    temperature=0.3,
    tags=("mlx", "rtx", "transfer", "portability"),
)

# Registry of built-in lenses
BUILTIN_LENSES: dict[str, ScoringLens] = {
    "convergence": CONVERGENCE_LENS,
    "efficiency": EFFICIENCY_LENS,
    "risk": RISK_LENS,
    "transfer": TRANSFER_LENS,
}


def get_lens(name: str) -> ScoringLens:
    """Look up a scoring lens by name.

    Args:
        name: Lens name (must be in BUILTIN_LENSES).

    Returns:
        The ScoringLens instance.

    Raises:
        KeyError: If the lens name is not found.
    """
    if name not in BUILTIN_LENSES:
        available = ", ".join(sorted(BUILTIN_LENSES))
        raise KeyError(f"Unknown lens {name!r}. Available: {available}")
    return BUILTIN_LENSES[name]


def register_lens(lens: ScoringLens) -> None:
    """Register a custom lens in the global registry.

    This allows extending the system with project-specific lenses at runtime.
    """
    BUILTIN_LENSES[lens.name] = lens


def list_lenses() -> list[dict[str, Any]]:
    """List all registered lenses with metadata."""
    return [
        {
            "name": lens.name,
            "description": lens.description,
            "temperature": lens.temperature,
            "tags": list(lens.tags),
        }
        for lens in sorted(BUILTIN_LENSES.values(), key=lambda l: l.name)
    ]


# ---------------------------------------------------------------------------
# TSV data loading
# ---------------------------------------------------------------------------

def load_results_tsv(path: str | Path) -> list[dict[str, str]]:
    """Load experiment results from a TSV file.

    Expected columns: commit, val_bpb, memory_gb, status, description
    (but accepts any TSV with a header row).

    Returns:
        List of row dicts keyed by column headers.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Results file not found: {path}")

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Results file is empty: {path}")

    lines = text.split("\n")
    if len(lines) < 2:
        raise ValueError(
            f"Results file needs at least a header and one data row: {path}"
        )

    header = lines[0].split("\t")
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = line.split("\t")
        # Pad or truncate to match header length
        row = {}
        for i, col in enumerate(header):
            row[col.strip()] = values[i].strip() if i < len(values) else ""
        rows.append(row)

    return rows


def summarize_data(rows: list[dict[str, str]], max_rows: int = 50) -> str:
    """Create a text summary of experiment data for the LLM prompt.

    Args:
        rows: Parsed TSV rows.
        max_rows: Maximum rows to include (to stay within context limits).

    Returns:
        Tab-separated text with header.
    """
    if not rows:
        return "(no data)"

    columns = list(rows[0].keys())
    lines = ["\t".join(columns)]
    for row in rows[:max_rows]:
        lines.append("\t".join(row.get(c, "") for c in columns))

    if len(rows) > max_rows:
        lines.append(f"... ({len(rows) - max_rows} more rows omitted)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama interaction
# ---------------------------------------------------------------------------

def _call_ollama(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
    temperature: float = 0.3,
    timeout_s: int = 180,
) -> str | None:
    """Call Ollama generate endpoint. Returns response text or None on error."""
    payload = {
        "model": model,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
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
        logger.warning("Ollama call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_findings(raw: str, lens_name: str) -> list[dict[str, Any]]:
    """Parse LLM response into structured findings.

    Handles JSON arrays, JSON wrapped in markdown fences, and falls back
    to extracting individual JSON objects if needed.

    Args:
        raw: Raw LLM response text.
        lens_name: Name of the lens (used to set category).

    Returns:
        List of finding dicts conforming to research_digest schema.
    """
    if not raw:
        return []

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    findings: list[dict[str, Any]] = []

    # Try parsing as JSON array
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            findings = parsed
        elif isinstance(parsed, dict):
            # Single finding wrapped in object
            findings = parsed.get("findings", [parsed])
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end > start:
            try:
                findings = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                logger.warning("Failed to parse findings from LLM response")
                return []

    # Validate and normalize each finding
    validated: list[dict[str, Any]] = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            continue
        validated.append({
            "id": f.get("id", f"SL-{i + 1:03d}"),
            "claim": str(f.get("claim", ""))[:200],
            "confidence": _clamp_float(f.get("confidence", 0.5), 0.0, 1.0),
            "actionable": bool(f.get("actionable", True)),
            "target": str(f.get("target", "unknown")),
            "effort": _normalize_effort(f.get("effort", "medium")),
            "category": lens_name,
        })

    return validated


def _clamp_float(value: Any, low: float, high: float) -> float:
    """Clamp a value to [low, high], coercing to float."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return (low + high) / 2
    return max(low, min(high, v))


def _normalize_effort(value: Any) -> str:
    """Normalize effort to one of: low, medium, high."""
    s = str(value).lower().strip()
    if s in ("low", "l", "small", "trivial", "easy"):
        return "low"
    if s in ("high", "h", "large", "hard", "significant"):
        return "high"
    return "medium"


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_lens(
    data_path: str | Path,
    lens_name: str,
    *,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a scoring lens against experiment data.

    Args:
        data_path: Path to results.tsv file.
        lens_name: Name of the lens to apply.
        model: Ollama model name.
        ollama_url: Ollama base URL.
        dry_run: If True, build prompt but skip LLM call.

    Returns:
        Dict with: lens, data_path, findings, prompt (if dry_run), error.
    """
    lens = get_lens(lens_name)
    rows = load_results_tsv(data_path)
    data_summary = summarize_data(rows)
    columns = list(rows[0].keys()) if rows else []

    user_prompt = USER_PROMPT_TEMPLATE.format(
        lens_name=lens.name,
        data_summary=data_summary,
        column_info=", ".join(columns),
        schema=FINDING_SCHEMA_DESCRIPTION,
    )

    result: dict[str, Any] = {
        "lens": lens.name,
        "data_path": str(data_path),
        "row_count": len(rows),
        "model": model,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "findings": [],
        "error": None,
    }

    if dry_run:
        result["prompt"] = {
            "system": lens.system_prompt,
            "user": user_prompt,
            "temperature": lens.temperature,
        }
        return result

    raw = _call_ollama(
        lens.system_prompt,
        user_prompt,
        model=model,
        base_url=ollama_url,
        temperature=lens.temperature,
    )

    if raw is None:
        result["error"] = "Ollama call failed (see logs)"
        return result

    findings = parse_findings(raw, lens.name)
    result["findings"] = findings
    return result


def findings_to_ledger_entries(
    findings: list[dict[str, Any]],
    lens_name: str,
) -> list[dict[str, Any]]:
    """Convert scoring lens findings to Open Brain ingestible format.

    Produces dicts compatible with LedgerEntry.create() for federation
    to Open Brain via client or federate-to-brain.py.
    """
    from hummbl_clp.core.models import LedgerEntry

    entries = []
    for f in findings:
        content = (
            f"[{lens_name}] {f.get('claim', '')}\n\n"
            f"Target: {f.get('target', 'unknown')}\n"
            f"Effort: {f.get('effort', 'medium')}\n"
            f"Actionable: {f.get('actionable', True)}"
        )
        entry = LedgerEntry.create(
            agent="scoring-lenses",
            vendor="local",
            model=DEFAULT_MODEL,
            entry_type="discovery",
            scope="project",
            content=content,
            confidence=f.get("confidence", 0.5),
            tags=(
                "scoring-lens",
                f"lens:{lens_name}",
                f"target:{f.get('target', 'unknown')}",
            ),
        )
        entries.append(entry.to_dict())
    return entries


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Scoring Lenses -- swappable analytical prompts for experiment data",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Run command
    p_run = subparsers.add_parser("run", help="Run a scoring lens on experiment data")
    p_run.add_argument("--lens", required=True, help="Lens name to apply")
    p_run.add_argument("--data", required=True, help="Path to results.tsv")
    p_run.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    p_run.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_URL,
        help=f"Ollama base URL (default: {DEFAULT_OLLAMA_URL})",
    )
    p_run.add_argument("--dry-run", action="store_true", help="Build prompt without calling LLM")
    p_run.add_argument(
        "--to-ledger", action="store_true",
        help="Also output findings as ledger entries for Open Brain ingestion",
    )

    # List command
    subparsers.add_parser("list", help="List available scoring lenses")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    if args.command == "list":
        lenses = list_lenses()
        for lens in lenses:
            tags = ", ".join(lens["tags"]) if lens["tags"] else ""
            print(f"  {lens['name']:15s} T={lens['temperature']:.1f}  {lens['description']}")
            if tags:
                print(f"  {'':15s} tags: {tags}")
        return 0

    if args.command == "run":
        try:
            result = run_lens(
                data_path=args.data,
                lens_name=args.lens,
                model=args.model,
                ollama_url=args.ollama_url,
                dry_run=args.dry_run,
            )
        except (FileNotFoundError, ValueError, KeyError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        print(json.dumps(result, indent=2))

        if getattr(args, "to_ledger", False) and result.get("findings"):
            entries = findings_to_ledger_entries(result["findings"], args.lens)
            print("\n--- Ledger Entries ---")
            print(json.dumps(entries, indent=2))

        return 0 if not result.get("error") else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
