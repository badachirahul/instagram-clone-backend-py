import asyncio
from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # user_id -> list of active WebSocket connections (multiple tabs supported)
        self._connections: defaultdict[int, list[WebSocket]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[user_id].append(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        # Use .get() — defaultdict would create a ghost entry for unknown user_ids
        conns = self._connections.get(user_id)
        if not conns:
            return
        if ws in conns:
            conns.remove(ws)
        if not conns:
            del self._connections[user_id]

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        conns = list(self._connections.get(user_id, []))
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    def broadcast_sync(self, user_ids: list[int], payload: dict) -> None:
        """
        Safe to call from synchronous route handlers (threadpool threads).
        Schedules async sends on the main event loop without blocking.
        """
        if self._loop is None or not self._loop.is_running():
            return
        for uid in user_ids:
            if uid in self._connections:
                asyncio.run_coroutine_threadsafe(
                    self.send_to_user(uid, payload),
                    self._loop,
                )


manager = ConnectionManager()
