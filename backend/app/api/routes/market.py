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
        # Supabase에서 OR 필터: ilike 사용
        query = query.or_(
            f"stock_name.ilike.%{search}%,stock_code.ilike.%{search}%"
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
    from app.main import app_state
    import json as _json

    # 1) Redis 캐시
    redis_client = app_state.get("redis")
    if redis_client:
        try:
            cached = await redis_client.get(f"price:{stock_code}")
            if cached:
                raw = _json.loads(cached)
                return StockPrice(
                    stock_code=raw.get("stock_code", stock_code),
                    current_price=raw.get("price", 0),
                    change_price=raw.get("change"),
                    change_rate=raw.get("change_rate"),
                    volume=raw.get("volume"),
                    high_price=raw.get("high"),
                    low_price=raw.get("low"),
                    open_price=raw.get("open"),
                    cached_at=raw.get("time"),
                )
        except Exception:
            pass

    # 2) KIS API 직접 호출
    try:
        from app.services.kis_api import get_kis_client

        kis = get_kis_client()
        price_data = await kis.get_current_price(stock_code)
        if price_data and price_data.get("price", 0) > 0:
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


@router.get("/indices", response_model=list[MarketIndex])
async def get_market_indices(
    clerk_user_id: ClerkUserId,
):
    """
    KOSPI/KOSDAQ 주요 지수를 조회합니다.

    - Redis 캐시에서 조회합니다.

    TODO: KIS API 연동 후 실시간 지수 데이터 캐시 구현
    """
    from app.main import app_state

    indices: list[MarketIndex] = []
    redis_client = app_state.get("redis")

    if redis_client:
        try:
            import json

            for code, name in [("0001", "KOSPI"), ("1001", "KOSDAQ")]:
                cached = await redis_client.get(f"index:{code}")
                if cached:
                    raw = json.loads(cached)
                    indices.append(MarketIndex(
                        index_code=raw.get("index_code", code),
                        index_name=raw.get("name", name),
                        current_value=raw.get("value", 0.0),
                        change_value=raw.get("change"),
                        change_rate=raw.get("change_rate"),
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
    time: str          # YYYY-MM-DD (일봉) 또는 HH:MM (분봉)
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
    - timeframe=1m → 당일 1분봉
    """
    from app.services.kis_api import get_kis_client
    from datetime import datetime, timedelta

    kis = get_kis_client()

    try:
        if timeframe == "1m":
            rows = await kis.get_minute_prices(stock_code, "090000")
            items = []
            for row in rows[:limit]:
                t = row.get("time", "")
                if len(t) >= 4:
                    t = f"{t[:2]}:{t[2:4]}"
                items.append(CandleItem(
                    time=t,
                    open=row.get("open", 0),
                    high=row.get("high", 0),
                    low=row.get("low", 0),
                    close=row.get("close", 0),
                    volume=row.get("volume", 0),
                ))
            return items
        else:
            # 일봉
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=limit * 2)).strftime("%Y%m%d")
            rows = await kis.get_daily_prices(stock_code, start_date, end_date)
            items = []
            for row in rows[:limit]:
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
            return items
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"KIS API 캔들 데이터 조회 실패: {str(e)}",
        )
