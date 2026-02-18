"""
한국투자증권 OpenAPI REST 클라이언트

토큰 자동 갱신, Rate Limit 쓰로틀링, 시세/종목 조회를 담당합니다.
모의투자 기준: 초당 5건 제한.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("kis_api")

# ── 토큰 매니저 ──────────────────────────────────────────────


class KISTokenManager:
    """
    한투 API 토큰 자동 관리.
    - Access Token: 24시간 유효, 만료 5분 전 자동 갱신
    - 6시간 내 중복 발급 시 동일 토큰 반환 (서버측 제한)
    - WebSocket 접속키: 별도 관리
    """

    def __init__(self):
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._ws_approval_key: str = ""
        self._ws_key_expires_at: float = 0.0
        self._last_token_issued_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_token_valid(self) -> bool:
        return bool(self._access_token) and time.time() < self._token_expires_at - 300

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def ws_approval_key(self) -> str:
        return self._ws_approval_key

    async def ensure_token(self) -> str:
        """유효한 토큰을 반환. 만료 임박 시 자동 갱신."""
        if self.is_token_valid:
            return self._access_token
        async with self._lock:
            if self.is_token_valid:
                return self._access_token
            await self._issue_token()
            return self._access_token

    async def _issue_token(self, retry: int = 3) -> None:
        """Access Token 발급/갱신."""
        settings = get_settings()
        url = f"{settings.KIS_BASE_URL}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": settings.KIS_APP_KEY,
            "appsecret": settings.KIS_APP_SECRET,
        }

        for attempt in range(retry):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json=body)
                    resp.raise_for_status()
                    data = resp.json()

                self._access_token = data["access_token"]
                # 토큰 유효시간: 24시간 (86400초)
                expires_in = int(data.get("expires_in", 86400))
                self._token_expires_at = time.time() + expires_in
                self._last_token_issued_at = time.time()
                logger.info(
                    f"KIS 토큰 발급 성공 (만료: {expires_in}초 후)"
                )
                return
            except Exception as e:
                logger.error(f"KIS 토큰 발급 실패 (시도 {attempt + 1}/{retry}): {e}")
                if attempt < retry - 1:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError("KIS 토큰 발급 실패: 모든 재시도 소진")

    async def get_ws_approval_key(self) -> str:
        """WebSocket 접속키 발급."""
        if self._ws_approval_key and time.time() < self._ws_key_expires_at - 300:
            return self._ws_approval_key

        settings = get_settings()
        url = f"{settings.KIS_BASE_URL}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": settings.KIS_APP_KEY,
            "secretkey": settings.KIS_APP_SECRET,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        self._ws_approval_key = data["approval_key"]
        # 접속키도 24시간 유효
        self._ws_key_expires_at = time.time() + 86400
        logger.info("KIS WebSocket 접속키 발급 성공")
        return self._ws_approval_key


# ── REST API 쓰로틀러 ────────────────────────────────────────


class KISThrottler:
    """
    모의투자 Rate Limit 대응: 초당 5건 제한.
    우선순위 큐: 주문(0) > 시세(1) > 종목정보(2) > 기타(3)
    """

    def __init__(self, max_per_second: int = 5):
        self._interval = 1.0 / max_per_second  # 200ms
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """다음 요청 가능 시점까지 대기."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last_request_time = time.time()


# ── KIS REST 클라이언트 ──────────────────────────────────────


class KISClient:
    """한국투자증권 REST API 클라이언트."""

    def __init__(self):
        self.token_manager = KISTokenManager()
        self.throttler = KISThrottler(max_per_second=5)
        self._settings = get_settings()

    async def _headers(self, tr_id: str) -> dict[str, str]:
        """API 호출용 공통 헤더."""
        token = await self.token_manager.ensure_token()
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self._settings.KIS_APP_KEY,
            "appsecret": self._settings.KIS_APP_SECRET,
            "tr_id": tr_id,
        }

    async def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        params: dict | None = None,
        body: dict | None = None,
        _retry: int = 0,
    ) -> dict[str, Any]:
        """쓰로틀링 적용된 API 호출 (429 시 최대 3회 재시도)."""
        MAX_RETRIES = 3
        await self.throttler.acquire()
        url = f"{self._settings.KIS_BASE_URL}{path}"
        headers = await self._headers(tr_id)

        async with httpx.AsyncClient(timeout=15) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            else:
                resp = await client.post(url, headers=headers, json=body)

            if resp.status_code == 429:
                if _retry >= MAX_RETRIES:
                    logger.error(f"KIS Rate Limit 초과 {MAX_RETRIES}회 재시도 실패: {path}")
                    raise httpx.HTTPStatusError(
                        f"KIS API rate limit exceeded after {MAX_RETRIES} retries",
                        request=resp.request,
                        response=resp,
                    )
                wait = 2 ** _retry  # 1s, 2s, 4s 지수 백오프
                logger.warning(f"KIS Rate Limit 초과, {wait}초 대기 후 재시도 ({_retry + 1}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
                return await self._request(method, path, tr_id, params, body, _retry=_retry + 1)

            resp.raise_for_status()
            return resp.json()

    # ── 시세 조회 ────────────────────────────────────────────

    async def get_current_price(self, stock_code: str) -> dict[str, Any]:
        """
        주식 현재가 조회.
        tr_id: FHKST01010100 (주식현재가 시세)
        """
        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",  # 주식
                "FID_INPUT_ISCD": stock_code,
            },
        )
        output = data.get("output", {})
        return {
            "stock_code": stock_code,
            "price": int(output.get("stck_prpr", 0)),          # 현재가
            "change": int(output.get("prdy_vrss", 0)),          # 전일대비
            "change_rate": float(output.get("prdy_ctrt", 0)),   # 등락률
            "volume": int(output.get("acml_vol", 0)),           # 누적거래량
            "open": int(output.get("stck_oprc", 0)),            # 시가
            "high": int(output.get("stck_hgpr", 0)),            # 고가
            "low": int(output.get("stck_lwpr", 0)),             # 저가
            "prev_close": int(output.get("stck_sdpr", 0)),      # 전일종가
            "market_cap": int(output.get("hts_avls", 0)),       # 시가총액(억)
        }

    async def get_orderbook(self, stock_code: str) -> dict[str, Any]:
        """
        호가 조회.
        tr_id: FHKST01010200 (주식현재가 호가/예상체결)
        """
        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            tr_id="FHKST01010200",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
            },
        )
        output = data.get("output1", {})
        asks = []
        bids = []
        for i in range(1, 11):
            ask_price = int(output.get(f"askp{i}", 0))
            ask_vol = int(output.get(f"askp_rsqn{i}", 0))
            bid_price = int(output.get(f"bidp{i}", 0))
            bid_vol = int(output.get(f"bidp_rsqn{i}", 0))
            if ask_price > 0:
                asks.append({"price": ask_price, "volume": ask_vol})
            if bid_price > 0:
                bids.append({"price": bid_price, "volume": bid_vol})
        return {
            "stock_code": stock_code,
            "asks": asks,   # 매도호가 (낮은 가격→높은 가격)
            "bids": bids,   # 매수호가 (높은 가격→낮은 가격)
            "total_ask_volume": int(output.get("total_askp_rsqn", 0)),
            "total_bid_volume": int(output.get("total_bidp_rsqn", 0)),
        }

    # ── 일봉/분봉 데이터 ────────────────────────────────────

    async def get_daily_prices(
        self, stock_code: str, start_date: str, end_date: str
    ) -> list[dict]:
        """
        일봉 데이터 조회 (최대 100건/회).
        tr_id: FHKST03010100 (주식현재가 일별)
        start_date, end_date: YYYYMMDD 형식
        """
        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",  # 일봉
                "FID_ORG_ADJ_PRC": "0",  # 수정주가 미반영
            },
        )
        rows = data.get("output2", [])
        return [
            {
                "time": row.get("stck_bsop_date", ""),  # YYYYMMDD
                "open": int(row.get("stck_oprc", 0)),
                "high": int(row.get("stck_hgpr", 0)),
                "low": int(row.get("stck_lwpr", 0)),
                "close": int(row.get("stck_clpr", 0)),
                "volume": int(row.get("acml_vol", 0)),
            }
            for row in rows
            if row.get("stck_bsop_date")
        ]

    async def get_minute_prices(
        self, stock_code: str, time_from: str = "090000"
    ) -> list[dict]:
        """
        당일 1분봉 조회 (30건/회, 당일만 가능).
        tr_id: FHKST03010200 (주식현재가 분봉)
        time_from: HHMMSS 형식
        """
        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            tr_id="FHKST03010200",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
                "FID_ETC_CLS_CODE": "",
                "FID_INPUT_HOUR_1": time_from,
                "FID_PW_DATA_INCU_YN": "Y",  # 과거 데이터 포함
            },
        )
        rows = data.get("output2", [])
        return [
            {
                "time": row.get("stck_cntg_hour", ""),  # HHMMSS
                "open": int(row.get("stck_oprc", 0)),
                "high": int(row.get("stck_hgpr", 0)),
                "low": int(row.get("stck_lwpr", 0)),
                "close": int(row.get("stck_prpr", 0)),
                "volume": int(row.get("cntg_vol", 0)),
            }
            for row in rows
            if row.get("stck_cntg_hour")
        ]

    # ── 종목 마스터 ──────────────────────────────────────────

    async def get_stock_info(self, stock_code: str) -> dict[str, Any]:
        """
        종목 기본 정보 조회.
        tr_id: CTPF1002R (주식 기본 조회)
        """
        try:
            data = await self._request(
                "GET",
                "/uapi/domestic-stock/v1/quotations/search-stock-info",
                tr_id="CTPF1002R",
                params={
                    "PRDT_TYPE_CD": "300",  # 주식
                    "PDNO": stock_code,
                },
            )
            output = data.get("output", {})
            return {
                "stock_code": stock_code,
                "stock_name": output.get("prdt_abrv_name", ""),
                "market": "KOSPI" if output.get("std_pdno", "")[:1] != "A" else "KOSDAQ",
                "sector": output.get("idx_bztp_scls_cd_name", ""),
            }
        except Exception as e:
            logger.warning(f"종목 정보 조회 실패 ({stock_code}): {e}")
            return {"stock_code": stock_code, "stock_name": "", "market": "", "sector": ""}

    # ── 시장 지수 ────────────────────────────────────────────

    async def get_market_index(self, index_code: str = "0001") -> dict[str, Any]:
        """
        시장 지수 조회 (KOSPI: 0001, KOSDAQ: 1001).
        tr_id: FHPUP02100000 (업종 현재가)
        """
        data = await self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-index-price",
            tr_id="FHPUP02100000",
            params={
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": index_code,
            },
        )
        output = data.get("output", {})
        return {
            "index_code": index_code,
            "name": "KOSPI" if index_code == "0001" else "KOSDAQ",
            "value": float(output.get("bstp_nmix_prpr", 0)),
            "change": float(output.get("bstp_nmix_prdy_vrss", 0)),
            "change_rate": float(output.get("bstp_nmix_prdy_ctrt", 0)),
            "volume": int(output.get("acml_vol", 0)),
        }


# ── 싱글턴 ────────────────────────────────────────────────

_kis_client: KISClient | None = None


def get_kis_client() -> KISClient:
    global _kis_client
    if _kis_client is None:
        _kis_client = KISClient()
    return _kis_client
