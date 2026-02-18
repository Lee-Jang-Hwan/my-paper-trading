"""
OUR Paper Trading - FastAPI 메인 애플리케이션

모의 주식투자 서비스의 백엔드 엔트리포인트입니다.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.dependencies import verify_ws_token
from app.db.supabase_client import get_supabase_client
from app.services.market_data import get_market_data_service
from app.services.stock_master import seed_major_stocks
from app.core.trading_engine import get_trading_engine
from app.agents.agent_manager import get_agent_manager
from app.agents.ws_broadcaster import get_agent_broadcaster

# ── 로깅 설정 ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")

# ── 앱 상태 (Redis, Supabase 등 공유 리소스) ─────────────────
app_state: dict[str, Any] = {}


# ── Lifespan (시작/종료 시 리소스 관리) ──────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 시작 시 Redis, Supabase 클라이언트를 초기화하고,
    종료 시 정리합니다.
    """
    settings = get_settings()

    # ── Startup ──────────────────────────────────────────────
    logger.info("=== OUR Paper Trading 서버 시작 ===")
    logger.info(f"환경: {settings.PYTHON_ENV}")

    # Redis 연결
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await redis_client.ping()
        app_state["redis"] = redis_client
        logger.info(f"Redis 연결 성공: {settings.REDIS_URL}")
    except Exception as exc:
        logger.warning(f"Redis 연결 실패 (캐시 없이 동작합니다): {exc}")
        app_state["redis"] = None

    # Supabase 클라이언트 초기화
    try:
        sb = get_supabase_client()
        app_state["supabase"] = sb
        logger.info(f"Supabase 연결 성공: {settings.supabase_url}")
    except Exception as exc:
        logger.error(f"Supabase 연결 실패: {exc}")
        app_state["supabase"] = None

    # 종목 마스터 시드 데이터 (최초 실행 시)
    if app_state.get("supabase"):
        try:
            await seed_major_stocks()
        except Exception as exc:
            logger.warning(f"종목 시드 데이터 삽입 실패: {exc}")

    # MarketDataService 시작 (KIS WebSocket + REST 폴링)
    try:
        market_svc = get_market_data_service(app_state.get("redis"))
        market_svc.set_broadcast_callback(ws_manager.broadcast)
        await market_svc.start()
        app_state["market_data"] = market_svc
        logger.info("MarketDataService 시작 완료")
    except Exception as exc:
        logger.warning(f"MarketDataService 시작 실패 (시세 없이 동작합니다): {exc}")
        app_state["market_data"] = None

    # 체결 엔진 시작
    try:
        engine = get_trading_engine(app_state.get("redis"))
        await engine.start()
        app_state["trading_engine"] = engine
        logger.info("체결 엔진 시작 완료")
    except Exception as exc:
        logger.warning(f"체결 엔진 시작 실패: {exc}")
        app_state["trading_engine"] = None

    # AI 에이전트 시스템 시작
    try:
        agent_mgr = get_agent_manager(app_state.get("redis"))
        # 에이전트 WebSocket 브로드캐스터 연결
        agent_ws = get_agent_broadcaster()
        agent_mgr.set_broadcaster(agent_ws.broadcast)
        app_state["agent_ws"] = agent_ws
        await agent_mgr.start()
        app_state["agent_manager"] = agent_mgr
        logger.info("AI 에이전트 시스템 시작 완료")
    except Exception as exc:
        logger.warning(f"AI 에이전트 시스템 시작 실패: {exc}")
        app_state["agent_manager"] = None

    logger.info("=== 서버 준비 완료 ===")

    yield  # 애플리케이션 실행 중

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("=== 서버 종료 중 ===")

    # AI 에이전트 시스템 종료
    if app_state.get("agent_manager"):
        await app_state["agent_manager"].stop()
        logger.info("AI 에이전트 시스템 종료")

    # 체결 엔진 종료
    if app_state.get("trading_engine"):
        await app_state["trading_engine"].stop()
        logger.info("체결 엔진 종료")

    # MarketDataService 종료
    if app_state.get("market_data"):
        await app_state["market_data"].stop()
        logger.info("MarketDataService 종료")

    # Redis 연결 종료
    if app_state.get("redis"):
        await app_state["redis"].aclose()
        logger.info("Redis 연결 종료")

    app_state.clear()
    logger.info("=== 서버 종료 완료 ===")


# ── FastAPI 앱 생성 ──────────────────────────────────────────
app = FastAPI(
    title="OUR Paper Trading API",
    description="한국 모의투자 서비스 백엔드 API",
    version="0.1.0",
    lifespan=lifespan,
)


# ── CORS 미들웨어 ────────────────────────────────────────────
settings = get_settings()

_allowed_origins: list[str] = []

if settings.CORS_ORIGINS:
    # 환경변수에서 쉼표로 구분된 오리진 사용
    _allowed_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

if settings.is_development:
    # 개발환경 기본 오리진
    for dev_origin in ["http://localhost:3000", "http://127.0.0.1:3000"]:
        if dev_origin not in _allowed_origins:
            _allowed_origins.append(dev_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


# ── 라우터 등록 ──────────────────────────────────────────────
from app.api.routes.profile import router as profile_router
from app.api.routes.account import router as account_router
from app.api.routes.market import router as market_router
from app.api.routes.orders import router as orders_router
from app.api.routes.agents import router as agents_router

app.include_router(profile_router)
app.include_router(account_router)
app.include_router(market_router)
app.include_router(orders_router)
app.include_router(agents_router)


# ── 헬스 체크 ────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health_check():
    """
    서버 상태 확인 엔드포인트.

    Redis 및 Supabase 연결 상태를 함께 반환합니다.
    """
    redis_ok = False
    if app_state.get("redis"):
        try:
            await app_state["redis"].ping()
            redis_ok = True
        except Exception:
            redis_ok = False

    return {
        "status": "ok",
        "service": "OUR Paper Trading API",
        "version": "0.1.0",
        "checks": {
            "redis": "connected" if redis_ok else "disconnected",
            "supabase": "connected" if app_state.get("supabase") else "disconnected",
            "agents": "running" if app_state.get("agent_manager") else "stopped",
        },
    }


# ── WebSocket 엔드포인트 (실시간 데이터 플레이스홀더) ────────

class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"WebSocket 연결: {websocket.client} "
            f"(현재 {len(self.active_connections)}개 연결)"
        )

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(
            f"WebSocket 해제: {websocket.client} "
            f"(현재 {len(self.active_connections)}개 연결)"
        )

    async def broadcast(self, message: dict):
        """모든 연결에 메시지를 브로드캐스트합니다."""
        import json
        text = json.dumps(message, ensure_ascii=False)
        disconnected: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(text)
            except Exception:
                disconnected.append(connection)
        for ws in disconnected:
            self.disconnect(ws)


ws_manager = ConnectionManager()


@app.websocket("/ws/realtime")
async def websocket_realtime(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    """
    실시간 시세 데이터 WebSocket 엔드포인트.

    인증: ?token=<JWT> 쿼리 파라미터로 Clerk JWT를 전달합니다.

    클라이언트 메시지 형식:
    - {"action": "subscribe", "stock_codes": ["005930", "000660"]}
    - {"action": "unsubscribe", "stock_codes": ["005930"]}
    - "ping" → {"type": "pong"} 응답
    """
    import json as _json

    # JWT 인증 검증
    if not token or not verify_ws_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await ws_manager.connect(websocket)
    market_svc = app_state.get("market_data")

    try:
        while True:
            raw = await websocket.receive_text()

            if raw == "ping":
                await websocket.send_text('{"type":"pong"}')
                continue

            try:
                msg = _json.loads(raw)
            except _json.JSONDecodeError:
                await websocket.send_text(
                    '{"type":"error","message":"잘못된 JSON 형식입니다."}'
                )
                continue

            action = msg.get("action", "")
            stock_codes = msg.get("stock_codes", [])

            if action == "subscribe" and stock_codes and market_svc:
                result = await market_svc.subscribe_realtime(stock_codes)
                await websocket.send_text(_json.dumps({
                    "type": "subscribe_ack",
                    "ws": result.get("ws", []),
                    "polling": result.get("polling", []),
                }, ensure_ascii=False))

            elif action == "unsubscribe" and stock_codes and market_svc:
                await market_svc.unsubscribe_realtime(stock_codes)
                await websocket.send_text(_json.dumps({
                    "type": "unsubscribe_ack",
                    "stock_codes": stock_codes,
                }, ensure_ascii=False))

            else:
                await websocket.send_text(
                    '{"type":"ack","message":"메시지를 수신했습니다."}'
                )

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ── Agent WebSocket 엔드포인트 ────────────────────────────────

agent_ws_manager = get_agent_broadcaster()


@app.websocket("/ws/agents")
async def websocket_agents(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    """
    에이전트 이벤트 실시간 스트리밍 WebSocket 엔드포인트.

    인증: ?token=<JWT> 쿼리 파라미터로 Clerk JWT를 전달합니다.
    """
    # JWT 인증 검증
    if not token or not verify_ws_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await agent_ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        agent_ws_manager.disconnect(websocket)


# ── uvicorn 직접 실행 ────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    _settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=_settings.FASTAPI_HOST,
        port=_settings.FASTAPI_PORT,
        reload=_settings.is_development,
        workers=_settings.FASTAPI_WORKERS if not _settings.is_development else 1,
    )
