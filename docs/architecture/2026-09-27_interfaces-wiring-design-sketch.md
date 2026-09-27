# Design Sketch — Wiring `core/interfaces.py` into OpenBrain

- **date**: 2026-09-27
- **author**: devin
- **status**: bounded sketch (no code). Prepared per the coronal intake
  recommendation, which assigns Option B a design-sketch-first lane with
  execution after the sealed CI gate (A-remote) is live.
- **intent**: INTENT-002 criterion 2 — "Wire `interfaces.py` abstract base
  classes into `hummbl-clp` OpenBrain retrieval pools."

## Current state (verified at `origin/main` `4917a38`)

`core/interfaces.py` (landed via #9) defines three surfaces with **zero
consumers**:

- `MemoryResult` — slotted result record (`source`, `entry_id`, `score`,
  `content`, `metadata`, `tokens`; `to_dict` rounds score to 4dp).
- `MemoryPool` — ABC: `name` property + `search(query, *, limit, since,
  **kwargs) -> list[MemoryResult]`.
- `SynthesisBackend` — ABC: `name` property + `generate(prompt, *,
  model_name, **kwargs) -> str | None`.

The extension layer duplicates both shapes:

- `extensions/retriever.py` — `OpenBrainRetriever` facade over 5 pools via
  private `_search_*` methods, plus its own `MemoryResult` (differs: required
  `metadata`, auto-estimates `tokens`, `to_dict` includes `tokens`).
- `extensions/consolidator.py` — `_ollama_generate` (Ollama
  `http://127.0.0.1:11434/api/generate`) used by `_synthesize_group`.
- `extensions/research_processor.py` — second Ollama call site.
- `extensions/server.py` — `OpenBrainState.search` serializes results via
  `r.to_dict()`; the serialized shape **is the HTTP API contract**.

## Design

### 1. Pool extraction (`retriever.py`)

Extract each private `_search_*` method into a `MemoryPool` implementation.
Naming below is provisional.

| Pool class | Wraps | Current source label |
|---|---|---|
| `LedgerPool` | `BM25Index` + `ensure_index` | `"ledger"` |
| `TextFilePool` | `_search_text_pool` body, parameterized by `name`, `search_dir`, `glob_pattern` | `"bus"`, `"briefings"` |
| `FindingsPool` | `_search_findings` (distinct parsing) | `"findings"` |
| `MemoryMdPool` | `_search_memory_md` | `"memory_md"` |

`bus` and `briefings` share `_search_text_pool`, so one parameterized
`TextFilePool` covers both — no duplicated pool classes.

`OpenBrainRetriever` becomes a fan-out compositor:

```python
class OpenBrainRetriever:
    def __init__(self, pools: list[MemoryPool], ...):
        self.pools = {p.name: p for p in pools}
```

- `search(...)` keeps its existing signature (`token_budget`, `scope`,
  `entry_type`, `sources`, `agent`) — it is the server-facing contract.
  Pool-specific filters pass through `**kwargs` on `MemoryPool.search`.
- Constructor gains a default that builds the current 5 pools from
  `state_dir`, preserving today's behavior for `server.py`.
- `ensure_index` moves into `LedgerPool`; the facade no longer owns index
  lifecycle.
- Retrieval logging (`log_retrieval`, `record_retrieval`) stays in the
  facade — it is cross-pool bookkeeping, not pool behavior.

### 2. `MemoryResult` unification

Delete the extension-local class; extensions import
`core.interfaces.MemoryResult`. Two deltas to reconcile first:

1. `to_dict` — extension version includes `tokens`; core omits it. Add
   `tokens` to core `to_dict` (additive; API contract preserved since the
   key already ships today).
2. Token auto-estimation — extension estimates on construction when
   `tokens=0`. Keep `_estimate_tokens` in the extension layer and pass an
   explicit value at each construction site rather than coupling core to
   the heuristic.

`metadata` optional-vs-required: make construction sites pass `metadata={}`
explicitly; keep core's optional default.

### 3. `SynthesisBackend` wiring (`consolidator.py`, `research_processor.py`)

```python
class OllamaBackend(SynthesisBackend):
    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL, model: str = DEFAULT_MODEL): ...
    @property
    def name(self) -> str: return "ollama"
    def generate(self, prompt, *, model_name=None, **kw) -> str | None:
        return _ollama_generate(prompt, model=model_name or self.model, base_url=self.base_url)
```

- `consolidator.run`/`_synthesize_group` and `research_processor` accept a
  `SynthesisBackend` (default `OllamaBackend()`), replacing their direct
  `_ollama_generate` calls.
- Graceful-degradation contract is preserved: `generate` returns `None` on
  failure, callers already handle `None`.
- Testability win: tests inject a stub backend instead of mocking HTTP.

### 4. Sequencing (per intake: A-remote gate first, then B in small PRs)

1. **PR-1** — `to_dict(tokens)` delta + extension `MemoryResult` deleted,
   construction sites updated. Mechanical, no behavior change; the new CI
   gate validates it.
2. **PR-2** — `TextFilePool` + `MemoryMdPool` + `FindingsPool` extraction;
   facade composes them.
3. **PR-3** — `LedgerPool` extraction (owns `ensure_index`); facade
   signature unchanged.
4. **PR-4** — `OllamaBackend` + backend injection into consolidator and
   research_processor.

Each PR independently mergeable; reverting any one leaves the rest intact.

### 5. Test plan

- Contract tests per pool: `isinstance(pool, MemoryPool)`, `name` stable,
  `search` honors `limit`/`since`, returns `core` `MemoryResult`.
- Facade fan-out: stub pools prove `sources=` filtering and token-budget
  truncation order preserved.
- Serialization: `OpenBrainState.search` output byte-identical for a
  fixture result (guards the HTTP contract).
- Backend: stub `SynthesisBackend` through consolidator proves `None`
  propagation (no-synthesis path) without Ollama running.

## Risks / open questions

- **`token_budget` stays facade-level** — `MemoryPool.search` has no budget
  concept; deliberate, budget is a composition concern.
- **`metadata` schema per pool differs** — kept free-form (`dict[str, Any]`);
  tightening is out of scope.
- **server.py unchanged** — it consumes the facade, not pools directly.
- **Import direction** — extensions import core; never the reverse.
- **Deferred**: whether `server.py`'s HTTP layer should expose pool names
  for health/status (nice-to-have; not in this sketch).
