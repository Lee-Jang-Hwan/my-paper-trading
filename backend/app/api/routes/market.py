"""
시장 데이터 라우트 - 종목 정보, 실시간 시세, 지수

종목 마스터(stock_master) 테이블과 Redis 캐시에서 데이터를 조회합니다.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.dependencies import ClerkUserId
from app.db.supabase_client import get_supabase_client

router = APIRouter(prefix="/api/market", tags=["market"])


# ── 응답 모델 ────────────────────────────────────────────────

class StockInfo(BaseModel):
    """종목 기본 정보"""
    stock_code: str
    stock_name: str
    market: Optional[str] = None        # KOSPI / KOSDAQ
    sector: Optional[str] = None        # 업종
    market_cap: Optional[int] = None    # 시가총액
    is_active: bool = True


class StockPrice(BaseModel):
    """종목 현재가"""
    stock_code: str
    stock_name: Optional[str] = None
    current_price: int
    change_price: Optional[int] = None        # 전일 대비 변동액
    change_rate: Optional[float] = None       # 전일 대비 변동률 (%)
    volume: Optional[int] = None              # 거래량
    high_price: Optional[int] = None          # 고가
    low_price: Optional[int] = None           # 저가
    open_price: Optional[int] = None          # 시가
    cached_at: Optional[str] = None           # 캐시 시각


class MarketIndex(BaseModel):
    """시장 지수"""
    index_code: str
    index_name: str
    current_value: float
    change_value: Optional[float] = None
    change_rate: Optional[float] = None
    cached_at: Optional[str] = None


class StockListResponse(BaseModel):
    """종목 목록 응답"""
    items: list[StockInfo]
    total: int
    page: int
    page_size: int


# ── 장 상태 ──────────────────────────────────────────────────

class MarketStatusResponse(BaseModel):
    """장 상태 응답"""
    is_open: bool
    phase: str          # "pre_market" / "open" / "closing_auction" / "closed"
    next_event: str
    next_event_time: str


@router.get("/status", response_model=MarketStatusResponse)
async def get_market_status_endpoint(
    clerk_user_id: ClerkUserId,
):
    """현재 장 상태(장 중/장 전/장 후)를 반환합니다."""
    from app.core.market_hours import get_market_status
    return MarketStatusResponse(**get_market_status())


# ── 라우트 핸들러 ────────────────────────────────────────────

@router.get("/stocks", response_model=StockListResponse)
async def list_stocks(
    clerk_user_id: ClerkUserId,
    market: Optional[str] = Query(None, description="시장 필터: KOSPI / KOSDAQ"),
    search: Optional[str] = Query(None, description="종목명 또는 종목코드 검색"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
):
    """
    종목 마스터 목록을 조회합니다.

    - market: KOSPI 또는 KOSDAQ로 필터링
    - search: 종목명 또는 종목코드로 검색 (부분 일치)
    - 페이지네이션 지원
    """
    sb = get_supabase_client()

    query = sb.table("stock_master").select("*", count="exact")

    # 활성 종목만
    query = query.eq("is_active", True)

    # 시장 필터
    if market:
        query = query.eq("market", market.upper())

    # 검색어 필터 (종목명 ilike 또는 종목코드 매칭)
    if search:
        # SQL ilike 와일드카드 이스케이프
        safe = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.or_(
            f"stock_name.ilike.%{safe}%,stock_code.ilike.%{safe}%"
        )

    # 페이지네이션
    offset = (page - 1) * page_size
    query = query.range(offset, offset + page_size - 1)

    # 종목코드 순 정렬
    query = query.order("stock_code")

    result = query.execute()

    items = [StockInfo(**row) for row in (result.data or [])]
    total = result.count if result.count is not None else len(items)

    return StockListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/price/{stock_code}", response_model=StockPrice)
async def get_stock_price(
    stock_code: str,
    clerk_user_id: ClerkUserId,
):
    """
    종목의 현재가를 조회합니다.

    1. Redis 캐시에서 조회
    2. 캐시 miss → KIS API 직접 호출
    3. 모두 실패 시 DB fallback (기본값)
    """
    # 1) MarketDataService 캐시 (인메모리 또는 Redis)
    try:
        from app.services.market_data import get_market_data_service
        mds = get_market_data_service()
        cached = await mds.get_price(stock_code)
        if cached:
            return StockPrice(
                stock_code=cached.get("stock_code", stock_code),
                current_price=cached.get("price", 0),
                change_price=cached.get("change"),
                change_rate=cached.get("change_rate"),
                volume=cached.get("volume"),
                high_price=cached.get("high"),
                low_price=cached.get("low"),
                open_price=cached.get("open"),
                cached_at=cached.get("time"),
            )
    except Exception:
        pass

    # 2) KIS API 직접 호출 + 캐시에 저장
    try:
        from app.services.kis_api import get_kis_client
        import json as _json

        kis = get_kis_client()
        price_data = await kis.get_current_price(stock_code)
        if price_data and price_data.get("price", 0) > 0:
            # 캐시에 저장 (다음 조회 시 캐시 히트)
            try:
                mds = get_market_data_service()
                from app.services.market_data import _get_ttl, PRICE_TTL, OFF_HOURS_PRICE_TTL
                ttl = _get_ttl(PRICE_TTL, OFF_HOURS_PRICE_TTL)
                cache_data = {
                    "type": "execution",
                    "stock_code": stock_code,
                    "price": price_data["price"],
                    "change": price_data.get("change", 0),
                    "change_rate": price_data.get("change_rate", 0.0),
                    "volume": price_data.get("volume", 0),
                    "open": price_data.get("open", 0),
                    "high": price_data.get("high", 0),
                    "low": price_data.get("low", 0),
                }
                await mds._cache.setex(
                    f"price:{stock_code}", ttl,
                    _json.dumps(cache_data, ensure_ascii=False),
                )
            except Exception:
                pass
            return StockPrice(
                stock_code=stock_code,
                current_price=price_data["price"],
                change_price=price_data.get("change"),
                change_rate=price_data.get("change_rate"),
                volume=price_data.get("volume"),
                high_price=price_data.get("high"),
                low_price=price_data.get("low"),
                open_price=price_data.get("open"),
                cached_at=None,
            )
    except Exception:
        pass

    # 3) DB fallback
    sb = get_supabase_client()
    result = (
        sb.table("stock_master")
        .select("stock_code, stock_name")
        .eq("stock_code", stock_code)
        .maybe_single()
        .execute()
    )

    if result.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"종목코드 '{stock_code}'를 찾을 수 없습니다.",
        )

    return StockPrice(
        stock_code=result.data["stock_code"],
        stock_name=result.data.get("stock_name"),
        current_price=0,
        change_price=0,
        change_rate=0.0,
        volume=0,
        cached_at=None,
    )


class BatchPriceItem(BaseModel):
    """배치 가격 조회 응답 항목"""
    stock_code: str
    current_price: int
    change_price: Optional[int] = None
    change_rate: Optional[float] = None


@router.get("/prices", response_model=list[BatchPriceItem])
async def get_batch_prices(
    clerk_user_id: ClerkUserId,
    codes: str = Query(..., description="쉼표로 구분된 종목코드 (최대 20개)"),
):
    """
    여러 종목의 현재가를 한 번에 조회합니다.
    KIS API를 순차 호출하므로 최대 20개로 제한합니다.
    """
    import asyncio

    stock_codes = [c.strip() for c in codes.split(",") if c.strip()][:20]
    if not stock_codes:
        return []

    from app.services.kis_api import get_kis_client
    from app.services.market_data import get_market_data_service

    kis = get_kis_client()
    results: list[BatchPriceItem] = []

    # 캐시에서 먼저 조회, miss된 것만 KIS API 호출
    mds = None
    try:
        mds = get_market_data_service()
    except Exception:
        pass

    miss_codes: list[str] = []

    for code in stock_codes:
        # 1) 캐시 먼저
        if mds:
            try:
                cached = await mds.get_price(code)
                if cached and cached.get("price", 0) > 0:
                    results.append(BatchPriceItem(
                        stock_code=code,
                        current_price=cached["price"],
                        change_price=cached.get("change"),
                        change_rate=cached.get("change_rate"),
                    ))
                    continue
            except Exception:
                pass
        miss_codes.append(code)

    # 2) 캐시 miss → KIS API 호출
    for code in miss_codes:
        try:
            price_data = await kis.get_current_price(code)
            if price_data and price_data.get("price", 0) > 0:
                results.append(BatchPriceItem(
                    stock_code=code,
                    current_price=price_data["price"],
                    change_price=price_data.get("change"),
                    change_rate=price_data.get("change_rate"),
                ))
            # KIS API 초당 호출 제한 방지
            await asyncio.sleep(0.05)
        except Exception:
            continue

    return results


@router.get("/indices", response_model=list[MarketIndex])
async def get_market_indices(
    clerk_user_id: ClerkUserId,
):
    """
    KOSPI/KOSDAQ 주요 지수를 조회합니다.

    - Redis 캐시에서 조회합니다.

    TODO: KIS API 연동 후 실시간 지수 데이터 캐시 구현
    """
    indices: list[MarketIndex] = []

    try:
        from app.services.market_data import get_market_data_service
        mds = get_market_data_service()
        for code, name in [("0001", "KOSPI"), ("1001", "KOSDAQ")]:
            cached = await mds.get_index(code)
            if cached:
                indices.append(MarketIndex(
                    index_code=cached.get("index_code", code),
                    index_name=cached.get("name", name),
                    current_value=cached.get("value", 0.0),
                    change_value=cached.get("change"),
                    change_rate=cached.get("change_rate"),
                ))
    except Exception:
        pass

    # 캐시에 데이터가 없으면 빈 리스트 반환 (장 마감 등)
    if not indices:
        # Placeholder: 데이터 없음을 나타내는 기본값
        indices = [
            MarketIndex(
                index_code="0001",
                index_name="KOSPI",
                current_value=0.0,
                change_value=None,
                change_rate=None,
                cached_at=None,
            ),
            MarketIndex(
                index_code="1001",
                index_name="KOSDAQ",
                current_value=0.0,
                change_value=None,
                change_rate=None,
                cached_at=None,
            ),
        ]

    return indices


# ── 캔들 데이터 ────────────────────────────────────────────


class CandleItem(BaseModel):
    """캔들 1건"""
    time: str          # YYYY-MM-DD (일봉) 또는 epoch seconds 문자열 (분봉)
    open: int
    high: int
    low: int
    close: int
    volume: int


@router.get("/candles/{stock_code}", response_model=list[CandleItem])
async def get_candles(
    stock_code: str,
    clerk_user_id: ClerkUserId,
    timeframe: str = Query("1d", description="1d / 1m"),
    limit: int = Query(100, ge=1, le=200),
):
    """
    종목 캔들(일봉/분봉) 데이터 조회.

    - timeframe=1d → 일봉 (최근 limit일)
    - timeframe=1m → 최근 거래일 1분봉
    """
    from app.services.kis_api import get_kis_client
    from datetime import datetime, timedelta, timezone

    kis = get_kis_client()
    KST = timezone(timedelta(hours=9))

    try:
        if timeframe == "1m":
            rows = await kis.get_minute_prices(stock_code, "090000")
            # 최근 거래일만 필터링 (KIS는 과거 데이터도 포함 가능)
            latest_date = None
            if rows:
                latest_date = rows[0].get("date", "")
            items = []
            for row in rows[:limit]:
                d = row.get("date", "")
                if latest_date and d != latest_date:
                    continue  # 최근 거래일 데이터만
                t = row.get("time", "")
                if len(d) == 8 and len(t) >= 4:
                    # YYYYMMDD + HHMMSS → epoch seconds
                    dt = datetime(
                        int(d[:4]), int(d[4:6]), int(d[6:8]),
                        int(t[:2]), int(t[2:4]), 0, tzinfo=KST,
                    )
                    epoch_str = str(int(dt.timestamp()))
                else:
                    continue
                items.append(CandleItem(
                    time=epoch_str,
                    open=row.get("open", 0),
                    high=row.get("high", 0),
                    low=row.get("low", 0),
                    close=row.get("close", 0),
                    volume=row.get("volume", 0),
                ))
            # KIS API는 최신순 반환 → 차트는 시간순(오름차순) 필요
            items.reverse()
            return items
        else:
            # 일봉 — 모의투자 API는 조회 범위가 제한적이므로 짧은 구간으로 분할 시도
            now = datetime.now(KST)
            end_date = now.strftime("%Y%m%d")

            rows = []
            # 30일씩 나누어 요청 (모의투자 서버 제한 대응)
            for chunk_idx in range(4):
                chunk_end = (now - timedelta(days=chunk_idx * 30)).strftime("%Y%m%d")
                chunk_start = (now - timedelta(days=(chunk_idx + 1) * 30)).strftime("%Y%m%d")
                try:
                    chunk_rows = await kis.get_daily_prices(stock_code, chunk_start, chunk_end)
                    if chunk_rows:
                        rows.extend(chunk_rows)
                    if len(rows) >= limit:
                        break
                except Exception:
                    break  # 조회 불가 구간이면 중단
            # 중복 제거 (여러 청크에서 겹칠 수 있음)
            seen_dates: set[str] = set()
            unique_rows: list[dict] = []
            for row in rows:
                t = row.get("time", "")
                if t and t not in seen_dates:
                    seen_dates.add(t)
                    unique_rows.append(row)

            items = []
            for row in unique_rows[:limit]:
                t = row.get("time", "")
                if len(t) == 8:
                    t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
                items.append(CandleItem(
                    time=t,
                    open=row.get("open", 0),
                    high=row.get("high", 0),
                    low=row.get("low", 0),
                    close=row.get("close", 0),
                    volume=row.get("volume", 0),
                ))
            # KIS API는 최신순 반환 → 차트는 시간순(오름차순) 필요
            items.reverse()
            return items
    except Exception as e:
        import logging
        logging.getLogger("market").warning(f"캔들 데이터 조회 실패 ({stock_code}): {e}")
        # 모의투자 API 제한 등으로 실패 시 빈 배열 반환 (502 대신)
        return []
