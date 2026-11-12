"""Unified assistant orchestration: intent routing, translation, RAG, video.

Pipeline for each user question:
1. Detect language (Hindi / regional via script detection).
2. Translate to English for CLIP embedding (CLIP is weak on non-Latin scripts).
3. Classify intent: video / doc / both (LLM with heuristic fallback).
4. Retrieve document chunks (RAG) and/or video evidence.
5. Build grounded prompt, call LLM, return answer WITH citations + evidence.
"""
from __future__ import annotations

import logging
import re

from app.services.rag import prompts
from app.services.rag.retriever import build_video_evidence, search_documents, search_video

logger = logging.getLogger(__name__)

_NON_LATIN = re.compile(r"[\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0C00-\u0C7F\u0D00-\u0D7F\u0E00-\u0E7F\u0400-\u04FF]")


def detect_language(text: str) -> str:
    if _NON_LATIN.search(text):
        return "hi" if re.search(r"[\u0900-\u097F]", text) else "other"
    return "en"


LANGUAGE_NAMES = {"en": "English", "hi": "Hindi"}


class RagOrchestrator:
    def __init__(self, llm, embedder, vector_store):
        self.llm = llm
        self.embedder = embedder
        self.vector_store = vector_store

    # ------------------------------------------------------------ internals
    def _translate(self, text: str) -> str:
        if detect_language(text) == "en":
            return text
        if self.llm.provider == "mock":
            # MockLLM cannot translate; return as-is (documented limitation)
            return text
        try:
            res = self.llm.chat_json(prompts.TRANSLATE_SYSTEM, f"QUESTION: {text}")
            translated = res.get("translated", "").strip()
            return translated or text
        except Exception as exc:  # noqa: BLE001
            logger.warning("translation failed: %s", exc)
            return text

    def _detect_intent(self, question: str) -> dict[str, bool]:
        try:
            if self.llm.provider != "mock":
                res = self.llm.chat_json(prompts.INTENT_SYSTEM, f"QUESTION: {question}")
                if isinstance(res, dict) and ("video" in res or "doc" in res):
                    return {
                        "video": bool(res.get("video", True)),
                        "doc": bool(res.get("doc", True)),
                    }
        except Exception as exc:  # noqa: BLE001
            logger.warning("intent detection failed (%s); using heuristics", exc)
        # heuristic fallback
        q = question.lower()
        video_hint = any(
            k in q
            for k in (
                "camera", "footage", "cctv", "video", "seen", "who is", "where is",
                "forklift", "person", "worker", "near", "zone", "after", "before",
                "right now", "now", "machine 3", "helmet", "dock", "storage",
            )
        )
        doc_hint = any(
            k in q
            for k in (
                "procedure", "sop", "safety", "guideline", "manual", "maintenance",
                "how do", "what is", "policy", "document", "step", "should",
                "lockout", "ppe", "fire", "emergency", "checklist", "rule",
            )
        )
        return {"video": video_hint or not doc_hint, "doc": doc_hint or not video_hint}

    # ------------------------------------------------------------ main entry
    def answer_question(self, message: str, include_video: bool = True) -> dict:
        lang = detect_language(message)
        q_en = self._translate(message)
        intent = self._detect_intent(q_en)
        if not include_video:
            intent["video"] = False

        doc_hits = []
        if intent.get("doc", True):
            doc_hits = search_documents(self.vector_store, self.embedder, q_en, top_k=6)

        video_hits = []
        if intent.get("video"):
            raw = search_video(self.vector_store, self.embedder, q_en, top_k=18)
            # dedupe by segment, best frame per segment
            seen: dict[str, object] = {}
            for h in sorted(raw, key=lambda r: r.score, reverse=True):
                seg = h.metadata.get("segment_id", "")
                if seg and seg not in seen:
                    seen[seg] = h
            video_hits = list(seen.values())[:8]

        lang_name = LANGUAGE_NAMES.get(lang, "English")
        system = prompts.RAG_SYSTEM
        user = prompts.build_rag_user(q_en, doc_hits[:6], video_hits, lang_name)

        try:
            answer = self.llm.chat(system, user)
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM call failed: %s", exc)
            from app.services.rag.llm.mock import MockLLM

            answer = MockLLM().chat(system, user)

        citations = []
        for h in doc_hits:
            meta = h.metadata
            citations.append(
                {
                    "document_id": meta.get("document_id"),
                    "filename": meta.get("filename", ""),
                    "page": meta.get("page", 0),
                    "section": meta.get("section", ""),
                    "score": round(h.score, 3),
                }
            )
        evidence = build_video_evidence(video_hits, limit=6)

        return {
            "answer": answer,
            "language": lang,
            "citations": citations,
            "video_evidence": evidence,
            "intent": intent,
            "provider": self.llm.provider,
        }
