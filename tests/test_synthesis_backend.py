"""Contract tests for SynthesisBackend wiring (INTENT-002 Option B, PR-4)."""

from __future__ import annotations

from pathlib import Path

from hummbl_clp.core.interfaces import SynthesisBackend
from hummbl_clp.core.ledger_writer import read_entries
from hummbl_clp.core.models import LedgerEntry
from hummbl_clp.extensions.consolidator import OllamaBackend, run_consolidation


class _StubBackend(SynthesisBackend):
    def __init__(self, response: str | None) -> None:
        self._response = response
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return "stub"

    def generate(
        self,
        prompt: str,
        *,
        model_name: str | None = None,
        **kwargs: object,
    ) -> str | None:
        self.calls.append(prompt)
        return self._response


def _write_ledger(path: Path, contents: list[str]) -> None:
    entries = [
        LedgerEntry.create(
            agent="devin",
            vendor="local",
            model="deepseek-flash",
            entry_type="discovery",
            scope="project",
            content=content,
        )
        for content in contents
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(entry.to_jsonl() for entry in entries) + "\n",
        encoding="utf-8",
    )


def test_ollama_backend_contract_and_graceful_degradation() -> None:
    backend = OllamaBackend(base_url="http://127.0.0.1:1", model="test-model")
    assert isinstance(backend, SynthesisBackend)
    assert backend.name == "ollama"
    # Unreachable server degrades to None instead of raising.
    assert backend.generate("hello") is None


def test_consolidator_uses_injected_backend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CLP_KILL_SWITCH_ENGAGED", raising=False)
    monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
    ledger = tmp_path / "cognition" / "ledger.jsonl"
    _write_ledger(ledger, [
        "zebra crossing signal analysis alpha",
        "zebra crossing signal analysis beta",
    ])

    stub = _StubBackend("SYNTHESIZED SUMMARY")
    result = run_consolidation(ledger_path=ledger, backend=stub)

    assert result["consolidated"] == 1
    assert stub.calls, "backend must receive the synthesis prompt"

    entries = read_entries(ledger_path=ledger, limit=999_999)
    consolidated = [e for e in entries if "consolidated" in e.tags]
    assert len(consolidated) == 1
    assert consolidated[0].content == "SYNTHESIZED SUMMARY"


def test_consolidator_none_propagation_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CLP_KILL_SWITCH_ENGAGED", raising=False)
    monkeypatch.setenv("CLP_ALLOW_UNSIGNED", "1")
    ledger = tmp_path / "cognition" / "ledger.jsonl"
    _write_ledger(ledger, [
        "zebra crossing signal analysis alpha",
        "zebra crossing signal analysis beta",
    ])

    stub = _StubBackend(None)
    result = run_consolidation(ledger_path=ledger, backend=stub)

    assert result["consolidated"] == 1
    entries = read_entries(ledger_path=ledger, limit=999_999)
    consolidated = [e for e in entries if "consolidated" in e.tags]
    assert consolidated[0].content.startswith("Consolidated from related entries:")
