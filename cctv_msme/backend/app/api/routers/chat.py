"""Unified assistant chat (RAG + video, multi-language)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db.models import User
from app.schemas import ChatRequest, ChatResponse, Citation, VideoEvidence
from app.services.analytics.service import log_search
from app.state import state

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, user: User = Depends(get_current_user)):
    include_video = body.include_video and user.role in ("supervisor", "admin")
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: state.orchestrator.answer_question(body.message, include_video=include_video),
    )
    citations = [Citation(**c) for c in result["citations"]]
    evidence = [VideoEvidence(**e) for e in result["video_evidence"]]
    log_search(
        user.id,
        user.username,
        body.message,
        "chat",
        {"intent": result["intent"]},
        len(citations) + len(evidence),
    )
    return ChatResponse(
        answer=result["answer"],
        language=result["language"],
        citations=citations,
        video_evidence=evidence,
        intent=result["intent"],
        provider=result["provider"],
    )
