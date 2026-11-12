"""WebSocket event stream: camera status, alerts, activity."""
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import ws_user_from_token
from app.services.activity import event_hub
from app.services.activity_feed import recent

router = APIRouter()


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket, token: str | None = None):
    user = ws_user_from_token(token)
    if user is None:
        await ws.close(code=4401)
        return
    await event_hub.connect(ws, user)
    try:
        # Initial payload: recent activity so the client hydrates immediately.
        # send_json cannot serialize datetimes, so encode with default=str.
        await ws.send_text(
            json.dumps({"type": "activity_history", "payload": {"items": recent(20)}}, default=str)
        )
        while True:
            await ws.receive_text()  # keepalive / ignore client messages
    except WebSocketDisconnect:
        pass
    finally:
        await event_hub.disconnect(ws)
