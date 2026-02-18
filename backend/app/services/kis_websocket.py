"""
한국투자증권 WebSocket 매니저

실시간 체결가/호가 수신 → Redis 캐싱 → 클라이언트 브로드캐스트.
세션당 최대 41종목 (체결+호가 합산) 제한 대응.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets

from app.config import get_settings
from app.services.kis_api import get_kis_client

logger = logging.getLogger("kis_ws")

# KIS WebSocket 데이터 구분
TR_TYPE_EXECUTION = "H0STCNT0"   # 실시간 체결
TR_TYPE_ORDERBOOK = "H0STASP0"   # 실시간 호가


class KISWebSocketManager:
    """
    한투 WebSocket 실시간 시세 매니저.

    - 최대 41종목 동적 구독 관리
    - 우선순위: 보유종목 > 현재 화면 종목 > 관심종목
    - 자동 재연결 (3초 간격, 최대 10회)
    - 데이터 파싱 → 콜백 호출 (Redis 저장, 클라이언트 전송)
    """

    MAX_SUBSCRIPTIONS = 41

    def __init__(self):
        self._ws: Any = None
        self._subscribed: set[str] = set()  # 현재 구독 중인 종목코드
        self._running = False
        self._reconnect_count = 0
        self._max_reconnect = 10
        self._on_execution: Callable[..., Coroutine] | None = None
        self._on_orderbook: Callable[..., Coroutine] | None = None

    @property
    def subscribed_count(self) -> int:
        return len(self._subscribed)

    @property
    def subscribed_codes(self) -> set[str]:
        return self._subscribed.copy()

    def set_callbacks(
        self,
        on_execution: Callable[..., Coroutine] | None = None,
        on_orderbook: Callable[..., Coroutine] | None = None,
    ):
        """데이터 수신 콜백 등록."""
        self._on_execution = on_execution
        self._on_orderbook = on_orderbook

    async def connect(self) -> None:
        """WebSocket 연결 시작 (백그라운드 태스크)."""
        if self._running:
            logger.warning("WebSocket 이미 실행 중")
            return

        self._running = True
        self._reconnect_count = 0
        asyncio.create_task(self._run_loop())
        logger.info("KIS WebSocket 매니저 시작")

    async def disconnect(self) -> None:
        """WebSocket 연결 종료."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._subscribed.clear()
        logger.info("KIS WebSocket 매니저 종료")

    async def subscribe(self, stock_codes: list[str]) -> list[str]:
        """
        종목 구독 추가.
        41종목 제한 초과 시 추가 불가한 종목 목록 반환.
        """
        added = []
        overflow = []

        for code in stock_codes:
            if code in self._subscribed:
                continue
            if len(self._subscribed) >= self.MAX_SUBSCRIPTIONS:
                overflow.append(code)
                continue
            await self._send_subscribe(code, subscribe=True)
            self._subscribed.add(code)
            added.append(code)

        if added:
            logger.info(f"구독 추가: {added} (현재 {self.subscribed_count}/{self.MAX_SUBSCRIPTIONS})")
        if overflow:
            logger.warning(f"구독 한도 초과: {overflow}")

        return overflow

    async def unsubscribe(self, stock_codes: list[str]) -> None:
        """종목 구독 해제."""
        removed = []
        for code in stock_codes:
            if code not in self._subscribed:
                continue
            await self._send_subscribe(code, subscribe=False)
            self._subscribed.discard(code)
            removed.append(code)

        if removed:
            logger.info(f"구독 해제: {removed} (현재 {self.subscribed_count}/{self.MAX_SUBSCRIPTIONS})")

    async def replace_subscription(
        self, remove_codes: list[str], add_codes: list[str]
    ) -> None:
        """기존 구독 해제 후 새 종목 구독 (동적 구독 관리)."""
        await self.unsubscribe(remove_codes)
        await self.subscribe(add_codes)

    # ── 내부 메서드 ──────────────────────────────────────────

    async def _run_loop(self) -> None:
        """WebSocket 수신 루프 (자동 재연결 포함)."""
        settings = get_settings()

        while self._running:
            try:
                kis_client = get_kis_client()
                approval_key = await kis_client.token_manager.get_ws_approval_key()

                async with websockets.connect(
                    settings.KIS_WS_URL,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    self._reconnect_count = 0
                    logger.info(f"KIS WebSocket 연결 성공: {settings.KIS_WS_URL}")

                    # 기존 구독 복원
                    for code in list(self._subscribed):
                        await self._send_subscribe(code, subscribe=True)

                    # 메시지 수신 루프
                    async for message in ws:
                        try:
                            await self._handle_message(message)
                        except Exception as e:
                            logger.error(f"메시지 처리 오류: {e}")

            except websockets.ConnectionClosed as e:
                logger.warning(f"WebSocket 연결 끊김: {e}")
            except Exception as e:
                logger.error(f"WebSocket 오류: {e}")

            # 재연결
            if self._running:
                self._reconnect_count += 1
                if self._reconnect_count > self._max_reconnect:
                    logger.error("WebSocket 최대 재연결 횟수 초과, 중지")
                    self._running = False
                    break
                wait = min(3 * self._reconnect_count, 30)
                logger.info(f"WebSocket 재연결 대기: {wait}초 ({self._reconnect_count}/{self._max_reconnect})")
                await asyncio.sleep(wait)

    async def _send_subscribe(self, stock_code: str, subscribe: bool = True) -> None:
        """구독/구독해제 메시지 전송."""
        if not self._ws:
            return

        settings = get_settings()
        kis_client = get_kis_client()

        try:
            approval_key = await kis_client.token_manager.get_ws_approval_key()
        except Exception:
            logger.error("WebSocket 접속키 발급 실패, 구독 메시지 전송 불가")
            return

        # 체결 구독
        msg = json.dumps({
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1" if subscribe else "2",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": TR_TYPE_EXECUTION,
                    "tr_key": stock_code,
                }
            },
        })

        try:
            await self._ws.send(msg)
        except Exception as e:
            logger.error(f"구독 메시지 전송 실패 ({stock_code}): {e}")

    async def _handle_message(self, raw: str | bytes) -> None:
        """수신 메시지 파싱 및 콜백 호출."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        # JSON 형식 (연결 확인, 에러 등)
        if raw.startswith("{"):
            data = json.loads(raw)
            header = data.get("header", {})
            tr_id = header.get("tr_id", "")

            if header.get("tr_type") == "P":
                # PINGPONG 응답
                return

            if "msg1" in data.get("body", {}):
                msg = data["body"]["msg1"]
                logger.debug(f"KIS WS 메시지: [{tr_id}] {msg}")
            return

        # 파이프(|) 구분 데이터 (실시간 체결/호가)
        parts = raw.split("|")
        if len(parts) < 4:
            return

        # 헤더: 암호화구분|TR유형|데이터건수|TR_ID
        tr_id = parts[1] if len(parts) > 1 else ""
        data_str = parts[3] if len(parts) > 3 else ""

        if tr_id == TR_TYPE_EXECUTION:
            parsed = self._parse_execution(data_str)
            if parsed and self._on_execution:
                await self._on_execution(parsed)

        elif tr_id == TR_TYPE_ORDERBOOK:
            parsed = self._parse_orderbook(data_str)
            if parsed and self._on_orderbook:
                await self._on_orderbook(parsed)

    def _parse_execution(self, data: str) -> dict[str, Any] | None:
        """실시간 체결 데이터 파싱."""
        fields = data.split("^")
        if len(fields) < 20:
            return None

        try:
            return {
                "type": "execution",
                "stock_code": fields[0],           # 종목코드
                "time": fields[1],                  # 체결시간 HHMMSS
                "price": int(fields[2]),            # 현재가
                "change": int(fields[4]),           # 전일대비
                "change_rate": float(fields[5]),    # 등락률
                "volume": int(fields[12]),          # 누적거래량
                "trade_volume": int(fields[8]),     # 체결거래량
                "open": int(fields[7]),             # 시가
                "high": int(fields[6]),             # 고가 (일중)
                "low": int(fields[9]),              # 저가 (일중)
            }
        except (ValueError, IndexError) as e:
            logger.debug(f"체결 데이터 파싱 오류: {e}")
            return None

    def _parse_orderbook(self, data: str) -> dict[str, Any] | None:
        """실시간 호가 데이터 파싱."""
        fields = data.split("^")
        if len(fields) < 40:
            return None

        try:
            stock_code = fields[0]
            asks = []
            bids = []
            # 매도호가 1~10 (fields 3~22), 매수호가 1~10 (fields 23~42)
            for i in range(10):
                ask_price = int(fields[3 + i * 2])
                ask_vol = int(fields[4 + i * 2])
                bid_price = int(fields[23 + i * 2])
                bid_vol = int(fields[24 + i * 2])
                if ask_price > 0:
                    asks.append({"price": ask_price, "volume": ask_vol})
                if bid_price > 0:
                    bids.append({"price": bid_price, "volume": bid_vol})

            return {
                "type": "orderbook",
                "stock_code": stock_code,
                "time": fields[1],
                "asks": asks,
                "bids": bids,
            }
        except (ValueError, IndexError) as e:
            logger.debug(f"호가 데이터 파싱 오류: {e}")
            return None


# ── 싱글턴 ────────────────────────────────────────────────

_ws_manager: KISWebSocketManager | None = None


def get_kis_ws_manager() -> KISWebSocketManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = KISWebSocketManager()
    return _ws_manager
