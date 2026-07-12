"""FastAPI server: WebSocket push to the dashboard + small REST API."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("server")
STATIC_DIR = Path(__file__).parent / "static"


class Hub:
    """Fan-out of engine events to every connected dashboard."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.last_state: dict = {}

    def broadcast(self, message: dict) -> None:
        """Callable from sync engine callbacks running inside the event loop."""
        if message.get("type") == "state":
            self.last_state = message
        if not self.clients:
            return
        payload = json.dumps(message)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for ws in list(self.clients):
            loop.create_task(self._send(ws, payload))

    async def _send(self, ws: WebSocket, payload: str) -> None:
        try:
            await ws.send_text(payload)
        except Exception:  # noqa: BLE001 - drop dead sockets quietly
            self.clients.discard(ws)


def create_app(runtime) -> FastAPI:
    """`runtime` is app.runtime.Runtime - wired in run.py."""
    app = FastAPI(title="Trade Copilot")
    hub: Hub = runtime.hub

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        hub.clients.add(ws)
        await ws.send_text(json.dumps({
            "type": "init",
            "settings": runtime.settings_dict(),
            "bars_1m": runtime.chart_bars(limit=240),
            "signals": runtime.journal.recent(30),
            "stats_today": runtime.journal.today_stats(),
            "stats_all": runtime.journal.stats(),
            "state": hub.last_state,
            "feed_mode": runtime.feed_mode,
            "symbol": runtime.symbol,
        }))
        try:
            while True:
                await ws.receive_text()   # dashboard is push-only; drain pings
        except WebSocketDisconnect:
            hub.clients.discard(ws)

    @app.post("/api/shutdown")
    async def shutdown():
        hub.broadcast({"type": "shutdown"})
        await asyncio.sleep(0.3)   # let the goodbye message reach dashboards
        runtime.shutdown_event.set()
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {
            "feed_mode": runtime.feed_mode,
            "symbol": runtime.symbol,
            "stale": runtime.feed_stale(),
            "clients": len(hub.clients),
        }

    @app.get("/api/settings")
    async def get_settings():
        return runtime.settings_dict()

    @app.post("/api/settings")
    async def post_settings(patch: dict):
        runtime.settings.update(patch)
        hub.broadcast({"type": "settings", "settings": runtime.settings_dict()})
        return runtime.settings_dict()

    @app.get("/api/stats")
    async def stats():
        return {"today": runtime.journal.today_stats(),
                "all": runtime.journal.stats()}

    @app.get("/api/signals")
    async def signals(limit: int = 50):
        return runtime.journal.recent(limit)

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
