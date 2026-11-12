"""Shift summary generation + export."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.db.models import Alert, Camera, Summary
from app.services.activity_feed import record as record_activity
from app.services.rag import prompts
from app.services.rag.prompts import build_summary_user
from app.utils.video import to_iso, utcnow

logger = logging.getLogger(__name__)

ENTITY_PROMPTS = {
    "forklift": "a forklift truck",
    "person": "a person or worker",
    "truck": "a delivery truck or lorry",
    "pallet": "pallets with boxes",
    "machine_activity": "industrial machinery operating",
    "helmet_worker": "a worker wearing a yellow safety helmet",
}


def generate_shift_summary(
    hours: int,
    title: str | None,
    username: str,
    zone: str | None,
    llm,
    embedder,
    vector_store,
) -> Summary:
    end = utcnow()
    start = end - timedelta(hours=hours)

    filters = {
        "modality": "video",
        "ts_epoch": {"$gte": start.timestamp(), "$lte": end.timestamp()},
    }
    if zone:
        filters["zone"] = zone
    hits = vector_store.get(filters=filters)

    by_camera: dict[int, dict] = {}
    for h in hits:
        meta = h.metadata
        cid = int(meta.get("camera_id", 0))
        row = by_camera.setdefault(
            cid,
            {
                "camera_id": cid,
                "camera_name": meta.get("camera_name", f"Camera {cid}"),
                "zone": meta.get("zone", ""),
                "frames": 0,
                "entities": set(),
                "thumbnails": [],
            },
        )
        row["frames"] += 1
        if len(row["thumbnails"]) < 6:
            row["thumbnails"].append(meta.get("thumbnail", ""))

    activity_rows = []
    for row in by_camera.values():
        entities = set()
        for thumb in row["thumbnails"]:
            frame = _load_thumb(thumb)
            if frame is None:
                continue
            try:
                emb = embedder.embed_image(frame)
                embs = embedder.embed_texts(list(ENTITY_PROMPTS.values()))
                sims = [float(emb @ e) for e in embs]
                best = max(range(len(sims)), key=lambda i: sims[i])
                if sims[best] > 0.20:
                    entities.add(list(ENTITY_PROMPTS.keys())[best])
            except Exception:  # noqa: BLE001
                continue
        activity_rows.append(
            {
                "camera_name": row["camera_name"],
                "zone": row["zone"],
                "frames": row["frames"],
                "entities": sorted(entities) or ["none detected"],
            }
        )
    activity_rows.sort(key=lambda r: r["frames"], reverse=True)

    db = SessionLocal()
    try:
        alerts = (
            db.query(Alert)
            .filter(Alert.timestamp >= start, Alert.timestamp <= end)
            .order_by(Alert.timestamp.desc())
            .all()
        )
        if zone:
            alerts = [a for a in alerts if a.zone == zone]
        cameras = db.query(Camera).filter(Camera.is_active.is_(True)).all()
        if zone:
            cameras = [c for c in cameras if c.zone == zone]
    finally:
        db.close()

    alert_lines = [
        f"{a.timestamp.strftime('%H:%M')} - {a.camera_name}: {a.description} (score {a.score:.2f})"
        for a in alerts
    ]

    data = {
        "window_start": start.strftime("%Y-%m-%d %H:%M UTC"),
        "window_end": end.strftime("%Y-%m-%d %H:%M UTC"),
        "cameras_active": len(cameras),
        "total_frames": len(hits),
        "activity_rows": activity_rows,
        "alerts": alert_lines,
    }

    system = prompts.SUMMARY_SYSTEM
    try:
        content = llm.chat(system, build_summary_user(data))
    except Exception as exc:  # noqa: BLE001
        logger.error("summary LLM call failed: %s", exc)
        content = _fallback_summary(data)

    tags = []
    try:
        if llm.provider != "mock":
            tag_res = llm.chat_json(prompts.TAGS_SYSTEM, f"DESCRIPTION: {content[:2000]}")
            tags = tag_res.get("tags", [])
    except Exception:  # noqa: BLE001
        pass
    if not tags:
        try:
            from app.services.rag.llm.mock import MockLLM

            tags = MockLLM().chat_json(prompts.TAGS_SYSTEM, f"DESCRIPTION: {content}").get("tags", [])
        except Exception:  # noqa: BLE001
            tags = ["operational-efficiency"]

    db = SessionLocal()
    try:
        summary = Summary(
            title=title or f"Shift Summary {start.strftime('%d %b %H:%M')} - {end.strftime('%H:%M')}",
            kind="shift",
            zone=zone or "General",
            content=content,
            created_by=username,
            window_start=start,
            window_end=end,
            tags_json={"tags": tags},
        )
        db.add(summary)
        db.commit()
        db.refresh(summary)
    finally:
        db.close()

    record_activity("summary", f"Shift summary generated for last {hours}h by {username}")
    return summary


def _fallback_summary(data: dict) -> str:
    lines = [f"Shift Overview: {data['window_start']} to {data['window_end']}"]
    lines.append(f"Cameras active: {data['cameras_active']} | Frames analyzed: {data['total_frames']}")
    lines.append("\nActivity by zone:")
    for row in data["activity_rows"][:10]:
        lines.append(f"- {row['camera_name']} ({row['zone']}): {row['frames']} frames, entities: {', '.join(row['entities'])}")
    lines.append("\nSafety alerts: " + (", ".join(data["alerts"]) if data["alerts"] else "none"))
    return "\n".join(lines)


def _load_thumb(thumb_rel: str):
    import cv2

    from app.core.config import get_settings

    if not thumb_rel:
        return None
    try:
        path = get_settings().data_dir / thumb_rel
        if path.exists():
            return cv2.imread(str(path))
        # Thumb may live in the shared bucket (indexed on another laptop).
        from app.services.media_storage import media_get

        data = media_get(thumb_rel)
        if data is None:
            return None
        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- export
def render_txt(summary: Summary) -> str:
    tags = summary.tags_json.get("tags", [])
    return (
        f"{summary.title}\n{'=' * len(summary.title)}\n"
        f"Window: {to_iso(summary.window_start)} -> {to_iso(summary.window_end)}\n"
        f"Generated by: {summary.created_by} at {to_iso(summary.created_at)}\n"
        f"Tags: {', '.join(tags) if tags else 'none'}\n\n"
        f"{summary.content}\n"
    )


def render_html(summary: Summary) -> str:
    tags = summary.tags_json.get("tags", [])
    body = html.escape(summary.content).replace("\n", "<br/>")
    tag_html = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in tags)
    return f"""<!doctype html><html><head><meta charset="utf-8"/>
<title>{html.escape(summary.title)}</title>
<style>
 body {{ font-family: Arial, sans-serif; margin: 40px; color: #1e293b; }}
 h1 {{ color: #0f172a; border-bottom: 3px solid #2563eb; padding-bottom: 8px; }}
 .meta {{ color: #64748b; font-size: 13px; margin-bottom: 16px; }}
 .tag {{ display: inline-block; background: #dbeafe; color: #1e40af; border-radius: 999px;
         padding: 2px 10px; margin-right: 6px; font-size: 12px; }}
 .content {{ line-height: 1.6; }}
</style></head><body>
<h1>{html.escape(summary.title)}</h1>
<div class="meta">Window: {to_iso(summary.window_start)} &rarr; {to_iso(summary.window_end)}<br/>
Generated by {html.escape(summary.created_by)} on {to_iso(summary.created_at)}</div>
<div>{tag_html}</div>
<div class="content">{body}</div>
</body></html>"""
