"""Shared test configuration for hummbl-clp security tests.

Ensures a clean environment for each test by clearing security-relevant
env vars that could leak between tests.
"""

from __future__ import annotations

import os

# Env vars that control fail-closed behavior -- must be clean between tests
_SECURITY_ENV_VARS = (
    "BUS_SIGNING_SECRET",
    "FEDERATION_SECRET",
    "OPEN_BRAIN_TOKEN",
    "CLP_ALLOW_UNSIGNED",
    "CLP_ALLOW_NO_AUTH",
    "COGNITION_LEDGER",
)


def pytest_runtest_setup(item) -> None:
    """Clear security env vars before each test to prevent leakage."""
    for var in _SECURITY_ENV_VARS:
        os.environ.pop(var, None)
