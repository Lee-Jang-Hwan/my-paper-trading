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

    - 우선 Redis 캐시에서 조회합니다.
    - 캐시에 없으면 DB fallback 후 404를 반환합니다.

    TODO: Redis 연동 후 실시간 시세 캐시에서 조회하도록 구현
    """
    from app.main import app_state

    # Redis에서 캐시된 시세 조회 시도
    redis_client = app_state.get("redis")
    if redis_client:
        try:
            import json

            cached = await redis_client.get(f"price:{stock_code}")
            if cached:
                raw = json.loads(cached)
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
            pass  # Redis 실패 시 DB fallback

    # DB fallback: stock_master에서 기본 정보라도 반환
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

    # 현재가 데이터가 없는 경우 (시장 마감 등) - 기본값 반환
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
