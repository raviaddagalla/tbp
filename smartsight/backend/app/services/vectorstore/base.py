"""Vector store abstraction (Chroma today; anything else later)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    id: str
    score: float  # cosine similarity, higher = better
    metadata: dict[str, Any]
    text: str = ""
    embedding: Any | None = field(default=None)


class VectorStore(ABC):
    @abstractmethod
    def add(self, ids: list[str], embeddings, metadatas: list[dict], texts: list[str] | None = None) -> None: ...

    @abstractmethod
    def query(self, embedding, top_k: int, filters: dict | None = None) -> list[SearchResult]: ...

    @abstractmethod
    def count(self, filters: dict | None = None) -> int: ...

    @abstractmethod
    def delete(self, ids: list[str] | None = None, filters: dict | None = None) -> int: ...

    @abstractmethod
    def name(self) -> str: ...
