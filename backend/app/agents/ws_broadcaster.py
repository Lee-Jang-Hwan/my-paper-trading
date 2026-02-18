"""
에이전트 WebSocket 브로드캐스터

에이전트 이벤트(대화 시작/턴 메시지/종료 등)를
연결된 모든 WebSocket 클라이언트에 실시간 전송합니다.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("agent_ws")


class AgentWSBroadcaster:
    """에이전트 이벤트 전용 WebSocket 연결 관리."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"Agent WS 연결: {websocket.client} "
            f"(현재 {len(self.active_connections)}개)"
        )

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(
            f"Agent WS 해제: {websocket.client} "
            f"(현재 {len(self.active_connections)}개)"
        )

    async def broadcast(self, event: dict[str, Any]):
        """모든 연결에 에이전트 이벤트를 브로드캐스트."""
        if not self.active_connections:
            return

        # timestamp 자동 추가
        if "timestamp" not in event:
            event["timestamp"] = datetime.now(timezone.utc).isoformat()

        text = json.dumps(event, ensure_ascii=False, default=str)
        disconnected: list[WebSocket] = []

        for ws in self.active_connections:
            try:
                await ws.send_text(text)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)


# ── 싱글턴 ─────────────────────────────────────────────────────

_broadcaster: AgentWSBroadcaster | None = None


def get_agent_broadcaster() -> AgentWSBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = AgentWSBroadcaster()
    return _broadcaster
