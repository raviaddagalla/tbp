"""Offline mock LLM.

Guarantees a working demo without any API key. Answers are constructed
deterministically FROM THE RETRIEVED CONTEXT ONLY (no hallucination by
construction) and explicitly say when the context does not cover the
question.
"""
from __future__ import annotations

import json
import logging
import re

from app.services.rag.llm.base import LLMClient

logger = logging.getLogger(__name__)

DONT_KNOW = "I don't have that information in the available documents."

VIDEO_KEYWORDS = (
    "camera", "footage", "video", "cctv", "seen", "who", "where", "zone",
    "forklift", "person", "worker", "machine", "dock", "storage", "truck",
    "near", "helmet", "at ", "movement", "after", "before", "6 pm", "now",
)
DOC_KEYWORDS = (
    "procedure", "sop", "safety", "guideline", "manual", "maintenance",
    "how do i", "what is", "policy", "document", "step", "should", "lockout",
    "ppe", "fire", "emergency", "checklist", "rule", "protocol",
)


class MockLLM(LLMClient):
    @property
    def provider(self) -> str:
        return "mock"

    # ---------------------------------------------------------------- chat
    def chat(self, system: str, user: str, temperature: float | None = None) -> str:
        if "TRANSLATE" in system.upper():
            return self._extract(user, "QUESTION") or user.strip()

        if "INTENT" in system.upper():
            q = (self._extract(user, "QUESTION") or "").lower()
            return json.dumps({"video": self._video(q), "doc": self._doc(q)})

        if "TAGS" in system.upper():
            q = (self._extract(user, "DESCRIPTION") or "").lower()
            return json.dumps(self._tags(q))

        return self._rag_answer(user)

    def chat_json(self, system: str, user: str, temperature: float | None = None) -> dict:
        raw = self.chat(system, user, temperature)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # ------------------------------------------------------------ internals
    @staticmethod
    def _extract(user: str, marker: str) -> str:
        m = re.search(rf"^{marker}:\s*(.+)$", user, re.MULTILINE)
        if m:
            return m.group(1).strip()
        for line in user.splitlines():
            if marker.lower() in line.lower():
                return line.split(":", 1)[-1].strip()
        return ""

    @staticmethod
    def _video(q: str) -> bool:
        return any(k in q for k in VIDEO_KEYWORDS) and not q.startswith(("what is", "how do"))

    @staticmethod
    def _doc(q: str) -> bool:
        return any(k in q for k in DOC_KEYWORDS) or not MockLLM._video(q)

    @staticmethod
    def _tags(q: str) -> dict:
        tags = []
        if any(k in q for k in ("safety", "helmet", "fire", "spill", "ppe", "emergency", "hazard")):
            tags.append("safety")
        if any(k in q for k in ("energy", "waste", "emission", "water", "environment", "spill")):
            tags.append("environmental")
        if any(k in q for k in ("output", "production", "downtime", "efficiency", "machine", "shift")):
            tags.append("operational-efficiency")
        return {"tags": tags}

    def _rag_answer(self, user: str) -> str:
        question = self._extract(user, "QUESTION") or "your question"
        doc_lines = self._section_lines(user, "CONTEXT DOCUMENTS", "VIDEO EVIDENCE")
        video_lines = self._section_lines(user, "VIDEO EVIDENCE", None)
        if not doc_lines and not video_lines:
            return DONT_KNOW

        parts = []
        if doc_lines:
            parts.append("Based on the available documents:")
            for line in doc_lines[:3]:
                title, body = _split_citation(line)
                snippet = body[:300] + ("..." if len(body) > 300 else "")
                parts.append(f"\n- {snippet}")
                if title:
                    parts.append(f"  (source: {title})")
        if video_lines:
            parts.append("Camera evidence was also found:")
            for line in video_lines[:3]:
                parts.append(f"\n- {line[:250]}")
        if not doc_lines:
            parts.append(
                "\nI could not find this in the available documents, "
                "but the camera evidence above may help."
            )
        if self.provider == "mock":
            parts.append(
                "\nNote: I'm running in offline demo mode (no LLM API key configured), "
                "so this is a direct extract from the retrieved results rather than a generated answer."
            )
        return "\n".join(parts)

    @staticmethod
    def _section_lines(user: str, start_marker: str, end_marker: str | None) -> list[str]:
        start_idx = user.find(start_marker)
        if start_idx < 0:
            return []
        end_idx = len(user)
        if end_marker:
            idx = user.find(end_marker, start_idx + len(start_marker))
            if idx >= 0:
                end_idx = idx
        block = user[start_idx + len(start_marker) : end_idx]
        return [
            line.strip()
            for line in block.splitlines()
            if line.strip().startswith(("- ", "[", "* "))
        ]


def _split_citation(line: str) -> tuple[str, str]:
    m = re.match(r"^-\s+\[([^\]]+)\]\s*(.*)$", line)
    if m:
        return m.group(1), m.group(2)
    return "", line
