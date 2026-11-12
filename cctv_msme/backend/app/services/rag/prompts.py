"""RAG prompts and context builders."""
from __future__ import annotations

from app.utils.video import to_iso

RAG_SYSTEM = """You are the Factory Intelligence Assistant for an MSME manufacturing plant.
You answer questions ONLY using the provided CONTEXT (retrieved documents and camera evidence).
STRICT RULES:
1. Ground every claim in the context. Never invent procedures, numbers, or facts.
2. If the context does not contain the information needed to answer, reply exactly:
   "I don't have that information in the available documents."
3. When you use a document, cite it inline like [file.pdf - page 2].
4. Keep answers concise and practical for a shop-floor worker.
5. If camera evidence is provided, summarize what the cameras show in the requested time window.
"""

INTENT_SYSTEM = """You classify a factory worker's question.
INTENT: Return a JSON object with boolean fields "video" (needs camera footage/search)
and "doc" (needs document/SOP knowledge). Most questions need both.
Example: {"video": true, "doc": true}"""

TRANSLATE_SYSTEM = (
    "You are a translator. Translate the user's QUESTION to English. "
    "If it is already English, return it unchanged. "
    'Return ONLY a JSON object like {"translated": "..."}'
)

TAGS_SYSTEM = """Classify the given factory report into compliance/ESG categories.
Return ONLY a JSON object {"tags": [...]} from:
"safety", "environmental", "operational-efficiency", "maintenance", "compliance".

Example: {"tags": ["safety", "operational-efficiency"]}"""

SUMMARY_SYSTEM = """You write factory shift summaries for supervisors.
Use ONLY the provided data (per-camera activity counts, detected entities, safety alerts).
Structure the report with these sections:
1. Shift Overview (window, cameras, total frames analyzed)
2. Activity by Zone/Camera
3. Safety Alerts & Incidents (if any)
4. Recommendations (advisory only, based strictly on the data)
Keep it factual; do not invent events that are not in the data."""

INCIDENT_SYSTEM = """You write a compliance-ready incident description for a factory safety alert.
Use ONLY the provided alert details and timeline data.
Structure: (1) Incident summary (2) Timeline of clips (3) Camera/zones involved
(4) Recommended next steps (advisory). Keep it factual and neutral."""


def build_rag_user(question: str, doc_chunks: list, video_evidence: list, language: str = "English") -> str:
    lines = [f"QUESTION: {question}", ""]
    if doc_chunks:
        lines.append("CONTEXT DOCUMENTS:")
        for c in doc_chunks:
            title = f"{c.metadata.get('filename','doc')} - page {c.metadata.get('page','?')}"
            section = c.metadata.get("section", "")
            lines.append(f"- [{title} | section: {section}] {c.text}")
        lines.append("")
    if video_evidence:
        lines.append("VIDEO EVIDENCE:")
        for v in video_evidence:
            lines.append(
                f"- [camera: {v.metadata.get('camera_name','')} | zone: {v.metadata.get('zone','')} "
                f"| time: {v.metadata.get('timestamp','')}] similarity {v.score:.2f} "
                f"- most similar sampled frame for the query"
            )
        lines.append("")
    lines.append(f"ANSWER IN LANGUAGE: {language}")
    return "\n".join(lines)


def build_summary_user(data: dict) -> str:
    lines = [
        f"SHIFT WINDOW: {data['window_start']} to {data['window_end']}",
        f"CAMERAS ACTIVE: {data['cameras_active']}",
        f"TOTAL FRAMES ANALYZED: {data['total_frames']}",
        "",
        "ACTIVITY BY CAMERA/ZONE:",
    ]
    for row in data["activity_rows"]:
        lines.append(
            f"- {row['camera_name']} ({row['zone']}): {row['frames']} frames, "
            f"entities seen: {', '.join(row['entities']) or 'none'}"
        )
    lines.append("")
    lines.append("SAFETY ALERTS IN WINDOW:")
    for a in data.get("alerts", []):
        lines.append(f"- {a}")
    if not data.get("alerts"):
        lines.append("- none")
    lines.append("")
    lines.append("DESCRIPTION: Please write the shift summary per the required structure.")
    return "\n".join(lines)


def build_incident_user(alert: dict, timeline: list[dict]) -> str:
    lines = [
        f"ALERT TYPE: {alert['alert_type']}",
        f"LOCATION: {alert['camera_name']} ({alert['zone']})",
        f"TIMESTAMP: {to_iso(alert['timestamp'])}",
        f"SIMILARITY SCORE: {alert['score']}",
        f"DETECTED DESCRIPTION: {alert['description']}",
        "",
        "TIMELINE OF AVAILABLE CLIPS (before/during/after):",
    ]
    for t in timeline:
        lines.append(f"- {t['start']}  ({t['segment_id']})")
    if not timeline:
        lines.append("- no surrounding clips available")
    return "\n".join(lines)
