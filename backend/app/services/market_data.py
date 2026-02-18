"""
시세 데이터 서비스

KIS API → Redis 캐싱 → 클라이언트 브로드캐스트 파이프라인.
WebSocket 실시간 데이터와 REST 폴링을 통합 관리합니다.
"""

import asyncio
import json
import logging
from datetime import datetime

import redis.asyncio as aioredis

from app.services.kis_api import get_kis_client
from app.services.kis_websocket import get_kis_ws_manager

logger = logging.getLogger("market_data")

# Redis 키 TTL (초)
PRICE_TTL = 60       # 시세: 1분 (WebSocket으로 계속 갱신)
ORDERBOOK_TTL = 30   # 호가: 30초
INDEX_TTL = 60       # 지수: 1분


class MarketDataService:
    """
    시세 데이터 통합 서비스.

    - WebSocket 수신 데이터 → Redis 저장
    - REST 폴링 (WebSocket 외 종목) → Redis 저장
    - Redis에서 현재가/호가/지수 조회
    - 클라이언트 WebSocket 브로드캐스트
    """

    def __init__(self, redis_client: aioredis.Redis | None):
        self._redis = redis_client
        self._ws_manager = get_kis_ws_manager()
        self._kis_client = get_kis_client()
        self._polling_task: asyncio.Task | None = None
        self._polling_codes: set[str] = set()  # REST 폴링 대상 종목
        self._broadcast_callback = None  # 클라이언트 브로드캐스트 함수

    def set_broadcast_callback(self, callback):
        """클라이언트 WebSocket 브로드캐스트 함수 등록."""
        self._broadcast_callback = callback

    async def start(self) -> None:
        """서비스 시작: WebSocket 연결 + 콜백 등록."""
        # WebSocket 콜백 등록
        self._ws_manager.set_callbacks(
            on_execution=self._on_ws_execution,
            on_orderbook=self._on_ws_orderbook,
        )
        await self._ws_manager.connect()

        # 시장 지수 최초 로드
        await self._update_indices()

        # REST 폴링 시작
        self._polling_task = asyncio.create_task(self._polling_loop())

        logger.info("MarketDataService 시작")

    async def stop(self) -> None:
        """서비스 종료."""
        if self._polling_task:
            self._polling_task.cancel()
        await self._ws_manager.disconnect()
        logger.info("MarketDataService 종료")

    # ── WebSocket 구독 관리 ──────────────────────────────────

    async def subscribe_realtime(self, stock_codes: list[str]) -> dict:
        """
        종목 실시간 구독 (WebSocket 우선, 초과 시 REST 폴링).
        Returns: {"ws": [...], "polling": [...]}
        """
        overflow = await self._ws_manager.subscribe(stock_codes)
        if overflow:
            self._polling_codes.update(overflow)
        return {
            "ws": [c for c in stock_codes if c not in overflow],
            "polling": overflow,
        }

    async def unsubscribe_realtime(self, stock_codes: list[str]) -> None:
        """종목 실시간 구독 해제."""
        await self._ws_manager.unsubscribe(stock_codes)
        self._polling_codes -= set(stock_codes)

    # ── Redis 조회 ───────────────────────────────────────────

    async def get_price(self, stock_code: str) -> dict | None:
        """Redis에서 현재가 조회."""
        if not self._redis:
            return None
        data = await self._redis.get(f"price:{stock_code}")
        return json.loads(data) if data else None

    async def get_orderbook(self, stock_code: str) -> dict | None:
        """Redis에서 호가 조회."""
        if not self._redis:
            return None
        data = await self._redis.get(f"orderbook:{stock_code}")
        return json.loads(data) if data else None

    async def get_index(self, index_code: str) -> dict | None:
        """Redis에서 시장 지수 조회."""
        if not self._redis:
            return None
        data = await self._redis.get(f"index:{index_code}")
        return json.loads(data) if data else None

    # ── WebSocket 콜백 (데이터 수신 시 호출) ────────────────

    async def _on_ws_execution(self, data: dict) -> None:
        """실시간 체결 수신 → Redis 저장 + 브로드캐스트."""
        stock_code = data["stock_code"]

        # Redis에 저장
        if self._redis:
            await self._redis.setex(
                f"price:{stock_code}",
                PRICE_TTL,
                json.dumps(data, ensure_ascii=False),
            )

        # 클라이언트에 브로드캐스트
        if self._broadcast_callback:
            await self._broadcast_callback({
                "type": "price_update",
                "data": data,
            })

    async def _on_ws_orderbook(self, data: dict) -> None:
        """실시간 호가 수신 → Redis 저장 + 브로드캐스트."""
        stock_code = data["stock_code"]

        if self._redis:
            await self._redis.setex(
                f"orderbook:{stock_code}",
                ORDERBOOK_TTL,
                json.dumps(data, ensure_ascii=False),
            )

        if self._broadcast_callback:
            await self._broadcast_callback({
                "type": "orderbook_update",
                "data": data,
            })

    # ── REST 폴링 ────────────────────────────────────────────

    async def _polling_loop(self) -> None:
        """WebSocket 비구독 종목 REST 폴링 (5초 간격)."""
        while True:
            try:
                await asyncio.sleep(5)

                if not self._polling_codes:
                    continue

                for code in list(self._polling_codes):
                    try:
                        price_data = await self._kis_client.get_current_price(code)
                        data = {
                            "type": "execution",
                            "stock_code": code,
                            "price": price_data["price"],
                            "change": price_data["change"],
                            "change_rate": price_data["change_rate"],
                            "volume": price_data["volume"],
                            "open": price_data["open"],
                            "high": price_data["high"],
                            "low": price_data["low"],
                            "time": datetime.now().strftime("%H%M%S"),
                        }
                        await self._on_ws_execution(data)
                    except Exception as e:
                        logger.debug(f"폴링 실패 ({code}): {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"폴링 루프 오류: {e}")
                await asyncio.sleep(5)

    async def _update_indices(self) -> None:
        """시장 지수 업데이트 (KOSPI, KOSDAQ)."""
        for index_code in ["0001", "1001"]:
            try:
                data = await self._kis_client.get_market_index(index_code)
                if self._redis:
                    await self._redis.setex(
                        f"index:{index_code}",
                        INDEX_TTL,
                        json.dumps(data, ensure_ascii=False),
                    )
            except Exception as e:
                logger.debug(f"지수 업데이트 실패 ({index_code}): {e}")


# ── 싱글턴 ────────────────────────────────────────────────

_market_data_service: MarketDataService | None = None


def get_market_data_service(redis_client=None) -> MarketDataService:
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService(redis_client)
    return _market_data_service
