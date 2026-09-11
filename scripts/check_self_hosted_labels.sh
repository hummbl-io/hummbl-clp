#!/usr/bin/env bash
# Check workflow files for disallowed self-hosted runner labels.
#
# Rec 3 from AAR aar-recs-implementation (2026-08-19): extract the guardrail
# bash logic from ci-policy-guardrails.yml into a standalone script so it
# can be tested locally without CI.
#
# Approved: [self-hosted, Windows, X64] (anvil-windows-hummbl-io)
#           [self-hosted, Linux]       (hummbl-runner-isolated)
# Disallowed: everything else with `self-hosted` in runs-on
#
# Usage:
#   bash scripts/check_self_hosted_labels.sh [path/to/file.yml ...]
#   bash scripts/check_self_hosted_labels.sh .github/workflows/  # directory
#
# Exit codes:
#   0 = no disallowed self-hosted labels
#   1 = one or more disallowed labels found
set -euo pipefail

VIOLATIONS=0
FILES=()

if [ "$#" -eq 0 ]; then
  # Default: scan .github/workflows/
  if [ -d ".github/workflows" ]; then
    for f in .github/workflows/*.yml .github/workflows/*.yaml; do
      [ -f "$f" ] && FILES+=("$f")
    done
  fi
else
  for arg in "$@"; do
    if [ -d "$arg" ]; then
      for f in "$arg"/*.yml "$arg"/*.yaml; do
        [ -f "$f" ] && FILES+=("$f")
      done
    elif [ -f "$arg" ]; then
      FILES+=("$arg")
    fi
  done
fi

if [ "${#FILES[@]}" -eq 0 ]; then
  echo "No workflow files to check."
  exit 0
fi

for f in "${FILES[@]}"; do
  while IFS= read -r line; do
    lineno=$(echo "$line" | cut -d: -f1)
    content=$(echo "$line" | cut -d: -f2-)
    # Approved: [self-hosted, Windows, X64] or [self-hosted, Linux]
    if echo "$content" | grep -qE 'runs-on:\s*\[self-hosted,\s*Windows,\s*X64\]'; then
      echo "  APPROVED  $f:L$lineno: $content"
    elif echo "$content" | grep -qE 'runs-on:\s*\[self-hosted,\s*Linux\]'; then
      echo "  APPROVED  $f:L$lineno: $content"
    else
      echo "  VIOLATION $f:L$lineno: $content"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  done < <(grep -nE '^\s*runs-on:.*self-hosted' "$f" || true)
done

if [ "$VIOLATIONS" -gt 0 ]; then
  echo ""
  echo "FAIL: $VIOLATIONS disallowed self-hosted label(s) found."
  echo "Use 'runs-on: ubuntu-latest' instead, or add 'timeout-minutes: 10'."
  echo "Approved self-hosted patterns: [self-hosted, Windows, X64], [self-hosted, Linux]"
  exit 1
fi
echo "PASS: no disallowed self-hosted labels."
