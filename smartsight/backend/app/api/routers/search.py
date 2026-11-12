"""Semantic search API."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.schemas import SearchRequest
from app.services.runtime import get_runtime
from app.services.search import counts, semantic_search

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])

EXAMPLE_QUERIES = [
    "a person wearing a red backpack",
    "a person in a blue shirt",
    "someone standing near a doorway",
    "a white car",
    "a bicycle",
    "a dog",
    "people boarding a bus",
]


@router.post("")
def search(body: SearchRequest) -> dict:
    runtime = get_runtime()
    try:
        result = semantic_search(
            runtime.embedder,
            body.query.strip(),
            mode=body.mode,
            limit=body.limit,
            source_type=body.source_type,
            recording_id=body.recording_id,
            object_class=body.object_class,
            start=body.start,
            end=body.end,
            min_score=body.min_score,
        )
    except Exception as exc:  # noqa: BLE001 - surface a clear error instead of a stack trace
        logger.exception("search failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Search is unavailable: {exc}") from exc
    return result


@router.get("/examples")
def examples() -> dict:
    return {"queries": EXAMPLE_QUERIES}


@router.get("/stats")
def stats() -> dict:
    return counts()
