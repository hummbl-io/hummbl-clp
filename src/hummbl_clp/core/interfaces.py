"""Abstract interfaces for OpenBrain decoupling.

Provides standard library-only base classes for memory retrieval
pools and synthesis backends, enabling the server extensions to
be decoupled from fleet-specific paths and models.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hummbl_clp.core.models import LedgerEntry


class MemoryResult:
    """A standardized result from a MemoryPool."""

    __slots__ = ("source", "entry_id", "score", "content", "metadata", "tokens")

    def __init__(
        self,
        *,
        source: str,
        entry_id: str,
        score: float,
        content: str,
        metadata: dict[str, Any] | None = None,
        tokens: int = 0,
    ) -> None:
        self.source = source
        self.entry_id = entry_id
        self.score = score
        self.content = content
        self.metadata = metadata or {}
        self.tokens = tokens

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source": self.source,
            "entry_id": self.entry_id,
            "score": round(self.score, 4),
            "content": self.content,
            "metadata": self.metadata,
            "tokens": self.tokens,
        }


class MemoryPool(abc.ABC):
    """Abstract interface for a queryable memory source."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The identifier name of this memory pool."""
        ...

    @abc.abstractmethod
    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        since: str | None = None,
        **kwargs: Any,
    ) -> list[MemoryResult]:
        """Execute a search against this memory pool.

        Parameters
        ----------
        query : str
            The natural language query.
        limit : int
            Maximum number of results to return.
        since : str | None
            Optional ISO timestamp to filter out older entries.
        **kwargs
            Additional implementation-specific filters.
        """
        ...


class SynthesisBackend(abc.ABC):
    """Abstract interface for a generative synthesis model backend."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """The identifier name of this synthesis backend."""
        ...

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        """Generate a synthesized response for the given prompt.

        Parameters
        ----------
        prompt : str
            The input context and instructions.
        model_name : str | None
            Optional explicit model identifier to request.
        **kwargs
            Additional generation parameters (e.g., temperature).

        Returns
        -------
        str | None
            The generated response, or None if the synthesis failed.
        """
        ...
