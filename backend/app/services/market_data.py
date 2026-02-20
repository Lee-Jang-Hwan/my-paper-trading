"""
시세 데이터 서비스

KIS API → 캐싱(Redis 또는 인메모리) → 클라이언트 브로드캐스트 파이프라인.
WebSocket 실시간 데이터와 REST 폴링을 통합 관리합니다.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis

from app.services.kis_api import get_kis_client
from app.services.kis_websocket import get_kis_ws_manager

logger = logging.getLogger("market_data")

# Redis 키 TTL (초)
PRICE_TTL = 60       # 시세: 1분 (WebSocket으로 계속 갱신)
ORDERBOOK_TTL = 30   # 호가: 30초
INDEX_TTL = 60       # 지수: 1분

# 장 외 시간 TTL (초) — 마지막 종가/지수를 8시간 유지
OFF_HOURS_PRICE_TTL = 28800
OFF_HOURS_ORDERBOOK_TTL = 28800
OFF_HOURS_INDEX_TTL = 28800


def _is_market_open_simple() -> bool:
    """간단한 장 중 판별 (market_hours 모듈 의존 없이)."""
    now = datetime.now(timezone(timedelta(hours=9)))  # KST
    if now.weekday() >= 5:  # 토/일
        return False
    t = now.hour * 60 + now.minute
    return 540 <= t <= 930  # 09:00 ~ 15:30


def _get_ttl(market_ttl: int, off_hours_ttl: int) -> int:
    """장 중이면 짧은 TTL, 장 외면 긴 TTL 반환."""
    return market_ttl if _is_market_open_simple() else off_hours_ttl


class InMemoryCache:
    """Redis 없이도 동작하는 인메모리 캐시. Redis와 동일한 get/setex 인터페이스."""

    def __init__(self):
        self._store: dict[str, tuple[str, float]] = {}  # key → (json_value, expire_timestamp)
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """만료 항목 정리 태스크 시작."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """정리 태스크 중지."""
        if self._cleanup_task:
            self._cleanup_task.cancel()

    async def get(self, key: str) -> str | None:
        """키에 해당하는 값을 반환. 만료된 경우 None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        if time.time() > expire_at:
            del self._store[key]
            return None
        return value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """TTL(초)과 함께 값 저장."""
        self._store[key] = (value, time.time() + ttl)

    async def _cleanup_loop(self) -> None:
        """5분마다 만료 항목 정리."""
        while True:
            try:
                await asyncio.sleep(300)
                now = time.time()
                expired = [k for k, (_, exp) in self._store.items() if now > exp]
                for k in expired:
                    del self._store[k]
                if expired:
                    logger.debug(f"InMemoryCache: {len(expired)}개 만료 항목 정리")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"InMemoryCache 정리 오류: {e}")


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
        self._cache: aioredis.Redis | InMemoryCache = redis_client or InMemoryCache()
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
        # 인메모리 캐시 정리 태스크 시작
        if isinstance(self._cache, InMemoryCache):
            await self._cache.start()
            logger.info("InMemoryCache 사용 (Redis 없음)")

        # WebSocket 콜백 등록
        self._ws_manager.set_callbacks(
            on_execution=self._on_ws_execution,
            on_orderbook=self._on_ws_orderbook,
        )
        await self._ws_manager.connect()

        # 시장 지수 최초 로드
        await self._update_indices()

        # 주요 종목 종가 미리 캐시 (장 외에도 가격 표시용)
        await self._preload_top_prices()

        # REST 폴링 시작
        self._polling_task = asyncio.create_task(self._polling_loop())

        logger.info("MarketDataService 시작")

    async def stop(self) -> None:
        """서비스 종료."""
        if self._polling_task:
            self._polling_task.cancel()
        if isinstance(self._cache, InMemoryCache):
            await self._cache.stop()
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
        """캐시에서 현재가 조회."""
        try:
            data = await self._cache.get(f"price:{stock_code}")
            return json.loads(data) if data else None
        except Exception:
            return None

    async def get_orderbook(self, stock_code: str) -> dict | None:
        """캐시에서 호가 조회."""
        try:
            data = await self._cache.get(f"orderbook:{stock_code}")
            return json.loads(data) if data else None
        except Exception:
            return None

    async def get_index(self, index_code: str) -> dict | None:
        """캐시에서 시장 지수 조회."""
        try:
            data = await self._cache.get(f"index:{index_code}")
            return json.loads(data) if data else None
        except Exception:
            return None

    # ── WebSocket 콜백 (데이터 수신 시 호출) ────────────────

    async def _on_ws_execution(self, data: dict) -> None:
        """실시간 체결 수신 → 캐시 저장 + 브로드캐스트."""
        stock_code = data["stock_code"]

        # 캐시에 저장 (장 외에는 긴 TTL)
        try:
            ttl = _get_ttl(PRICE_TTL, OFF_HOURS_PRICE_TTL)
            await self._cache.setex(
                f"price:{stock_code}",
                ttl,
                json.dumps(data, ensure_ascii=False),
            )
        except Exception as e:
            logger.debug(f"캐시 저장 실패 (price:{stock_code}): {e}")

        # 클라이언트에 브로드캐스트
        if self._broadcast_callback:
            await self._broadcast_callback({
                "type": "price_update",
                "data": data,
            })

    async def _on_ws_orderbook(self, data: dict) -> None:
        """실시간 호가 수신 → 캐시 저장 + 브로드캐스트."""
        stock_code = data["stock_code"]

        try:
            ttl = _get_ttl(ORDERBOOK_TTL, OFF_HOURS_ORDERBOOK_TTL)
            await self._cache.setex(
                f"orderbook:{stock_code}",
                ttl,
                json.dumps(data, ensure_ascii=False),
            )
        except Exception as e:
            logger.debug(f"캐시 저장 실패 (orderbook:{stock_code}): {e}")

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
                ttl = _get_ttl(INDEX_TTL, OFF_HOURS_INDEX_TTL)
                await self._cache.setex(
                    f"index:{index_code}",
                    ttl,
                    json.dumps(data, ensure_ascii=False),
                )
            except Exception as e:
                logger.debug(f"지수 업데이트 실패 ({index_code}): {e}")

    async def _preload_top_prices(self) -> None:
        """서버 시작 시 MVP 종목의 현재가(종가)를 캐시에 미리 로드."""
        # MVP 10종목 (KIS 모의투자 API 검증 완료)
        top_codes = [
            "005930", "000660", "005380", "035420", "035720",
            "068270", "051910", "066570", "000270", "105560",
        ]

        loaded = 0
        for code in top_codes:
            try:
                price_data = await self._kis_client.get_current_price(code)
                if price_data and price_data.get("price", 0) > 0:
                    data = {
                        "type": "execution",
                        "stock_code": code,
                        "price": price_data["price"],
                        "change": price_data.get("change", 0),
                        "change_rate": price_data.get("change_rate", 0.0),
                        "volume": price_data.get("volume", 0),
                        "open": price_data.get("open", 0),
                        "high": price_data.get("high", 0),
                        "low": price_data.get("low", 0),
                        "time": datetime.now(timezone(timedelta(hours=9))).strftime("%H%M%S"),
                    }
                    ttl = _get_ttl(PRICE_TTL, OFF_HOURS_PRICE_TTL)
                    await self._cache.setex(
                        f"price:{code}", ttl,
                        json.dumps(data, ensure_ascii=False),
                    )
                    loaded += 1
                await asyncio.sleep(0.2)  # Rate limit 방지
            except Exception as e:
                logger.debug(f"종가 프리로드 실패 ({code}): {e}")

        logger.info(f"종가 프리로드 완료: {loaded}/{len(top_codes)}종목")


# ── 싱글턴 ────────────────────────────────────────────────

_market_data_service: MarketDataService | None = None


def get_market_data_service(redis_client=None) -> MarketDataService:
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService(redis_client)
    return _market_data_service
