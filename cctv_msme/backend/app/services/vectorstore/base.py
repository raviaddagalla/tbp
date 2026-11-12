"""Vector store abstraction.

Repository/interface pattern so the MVP can run on Chroma or a
zero-dependency NumPy store, and later swap to Milvus/Weaviate/Pinecone
by implementing this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    id: str
    score: float  # cosine similarity in [0, 1], higher = better
    metadata: dict[str, Any]
    text: str = field(default="")
    embedding: Any | None = None  # populated by get() so offline jobs can pool vectors


class VectorStore(ABC):
    """Single collection holding both video-frame and document-chunk
    embeddings, distinguished by metadata['modality']."""

    @abstractmethod
    def add(self, ids: list[str], embeddings, metadatas: list[dict], texts: list[str] | None = None) -> None:
        ...

    @abstractmethod
    def query(self, embedding, top_k: int, filters: dict | None = None) -> list[SearchResult]:
        ...

    @abstractmethod
    def get(self, filters: dict | None = None, limit: int | None = None) -> list[SearchResult]:
        """Return stored entries (sorted by insertion) matching filters."""

    @abstractmethod
    def count(self, filters: dict | None = None) -> int:
        ...

    @abstractmethod
    def delete(self, ids: list[str] | None = None, filters: dict | None = None) -> int:
        """Delete by explicit ids and/or by metadata filter. Returns count deleted."""

    @abstractmethod
    def compact(self) -> dict:
        """Rebuild/compact the underlying index to bound tombstone bloat.
        Returns a small status dict for logging."""
        ...

    @abstractmethod
    def name(self) -> str:
        ...
