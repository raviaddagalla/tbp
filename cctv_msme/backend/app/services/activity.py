"""WebSocket event hub: camera health, alerts, activity feed."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class EventHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._users: dict[WebSocket, Any] = {}  # ws -> user (for zone-scoped delivery)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user: Any = None) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
            if user is not None:
                self._users[ws] = user

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
            self._users.pop(ws, None)

    def _user_can_see(self, user: Any, event_type: str, payload: dict[str, Any]) -> bool:
        """Zone-restricted users only receive events for their own zone."""
        if user is None:
            return True
        zone = getattr(user, "zone", None)
        if user.role in ("worker", "supervisor") and zone and event_type == "alert":
            return payload.get("zone") == zone
        return True

    async def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        message = json.dumps({"type": event_type, "payload": payload}, default=str)
        dead = []
        async with self._lock:
            for ws in list(self._connections):
                if not self._user_can_see(self._users.get(ws), event_type, payload):
                    continue
                try:
                    await ws.send_text(message)
                except Exception:  # noqa: BLE001
                    dead.append(ws)
            for ws in dead:
                self._connections.discard(ws)
                self._users.pop(ws, None)


event_hub = EventHub()
