"""
주문 라우트 - 모의 매매 주문 처리

시장가/지정가 주문 생성, 주문 목록 조회, 주문 취소 기능을 제공합니다.
한국 주식시장의 호가단위(tick size) 규정을 검증합니다.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies import ClerkUserId
from app.db.supabase_client import get_supabase_client
from app.core.trading_engine import get_trading_engine

router = APIRouter(prefix="/api/orders", tags=["orders"])


# ── 열거형 ───────────────────────────────────────────────────

class OrderType(str, Enum):
    """주문 유형"""
    MARKET = "market"   # 시장가
    LIMIT = "limit"     # 지정가


class OrderSide(str, Enum):
    """주문 방향"""
    BUY = "buy"     # 매수
    SELL = "sell"    # 매도


class OrderStatus(str, Enum):
    """주문 상태"""
    PENDING = "pending"         # 대기
    FILLED = "filled"           # 체결
    PARTIALLY_FILLED = "partially_filled"  # 부분 체결
    CANCELLED = "cancelled"     # 취소
    REJECTED = "rejected"       # 거부


# ── 한국 주식시장 호가단위 (가격대별 호가단위) ────────────────

def get_tick_size(price: int) -> int:
    """
    주어진 가격에 대한 호가단위(tick size)를 반환합니다.

    한국거래소 호가단위 규정:
      < 2,000원    : 1원
      < 5,000원    : 5원
      < 20,000원   : 10원
      < 50,000원   : 50원
      < 200,000원  : 100원
      < 500,000원  : 500원
      >= 500,000원 : 1,000원
    """
    if price < 2_000:
        return 1
    elif price < 5_000:
        return 5
    elif price < 20_000:
        return 10
    elif price < 50_000:
        return 50
    elif price < 200_000:
        return 100
    elif price < 500_000:
        return 500
    else:
        return 1_000


def validate_tick_size(price: int) -> bool:
    """주문 가격이 호가단위에 맞는지 검증합니다."""
    tick = get_tick_size(price)
    return price % tick == 0


def round_to_tick(price: int) -> int:
    """주문 가격을 호가단위에 맞게 내림합니다."""
    tick = get_tick_size(price)
    return (price // tick) * tick


# ── 요청/응답 모델 ───────────────────────────────────────────

class OrderCreateRequest(BaseModel):
    """주문 생성 요청"""
    account_id: str = Field(..., description="계좌 ID")
    stock_code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="종목코드 (6자리 숫자)",
    )
    order_type: OrderType = Field(..., description="주문 유형: market(시장가) / limit(지정가)")
    order_side: OrderSide = Field(..., description="주문 방향: buy(매수) / sell(매도)")
    quantity: int = Field(..., gt=0, description="주문 수량 (1주 이상)")
    price: Optional[int] = Field(
        None,
        gt=0,
        description="주문 가격 (지정가 주문 시 필수, 시장가 주문 시 무시)",
    )

    @field_validator("price")
    @classmethod
    def validate_price_tick_size(cls, v: Optional[int], info) -> Optional[int]:
        """지정가 주문의 호가단위를 검증합니다."""
        if v is not None and v > 0:
            if not validate_tick_size(v):
                tick = get_tick_size(v)
                corrected = round_to_tick(v)
                raise ValueError(
                    f"주문 가격 {v:,}원은 호가단위({tick:,}원)에 맞지 않습니다. "
                    f"{corrected:,}원 또는 {corrected + tick:,}원으로 주문해 주세요."
                )
        return v


class OrderResponse(BaseModel):
    """주문 응답"""
    id: str
    account_id: str
    stock_code: str
    stock_name: Optional[str] = None
    order_type: str
    side: str
    quantity: int
    price: Optional[int] = None
    filled_quantity: Optional[int] = 0
    filled_price: Optional[int] = None
    status: str
    created_at: Optional[str] = None
    filled_at: Optional[str] = None


class OrderListResponse(BaseModel):
    """주문 목록 응답"""
    items: list[OrderResponse]
    total: int


# ── 라우트 핸들러 ────────────────────────────────────────────

@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(
    body: OrderCreateRequest,
    clerk_user_id: ClerkUserId,
):
    """
    새 주문을 생성합니다.

    - **시장가(market)**: 현재 시세로 즉시 체결 시도
    - **지정가(limit)**: 지정한 가격으로 주문 등록 (체결 대기)

    주문 생성 전 검증:
    1. 계좌 소유권 확인
    2. 지정가 주문의 호가단위 검증
    3. 매수 시 잔고 확인 / 매도 시 보유 수량 확인
    """
    sb = get_supabase_client()

    # 1. 계좌 소유권 확인
    account_result = (
        sb.table("accounts")
        .select("*")
        .eq("id", body.account_id)
        .eq("clerk_user_id", clerk_user_id)
        .maybe_single()
        .execute()
    )

    if account_result.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="계좌를 찾을 수 없거나 권한이 없습니다.",
        )

    account = account_result.data

    # 2. 지정가 주문 시 가격 필수 검증
    if body.order_type == OrderType.LIMIT and body.price is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="지정가 주문에는 가격(price)이 필수입니다.",
        )

    # 3. 매수 시 잔고 확인 (지정가 기준 간이 확인)
    if body.order_side == OrderSide.BUY and body.price is not None:
        estimated_cost = body.price * body.quantity
        if estimated_cost > account["balance"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"잔고가 부족합니다. "
                       f"필요금액: {estimated_cost:,}원, "
                       f"보유잔고: {account['balance']:,}원",
            )

    # 4. 매도 시 보유 수량 확인
    if body.order_side == OrderSide.SELL:
        holdings_result = (
            sb.table("holdings")
            .select("quantity")
            .eq("account_id", body.account_id)
            .eq("stock_code", body.stock_code)
            .maybe_single()
            .execute()
        )
        held_qty = holdings_result.data["quantity"] if holdings_result.data else 0
        if held_qty < body.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"보유 수량이 부족합니다. "
                       f"매도 수량: {body.quantity:,}주, "
                       f"보유 수량: {held_qty:,}주",
            )

    # 5. 종목명 조회
    stock_result = (
        sb.table("stock_master")
        .select("stock_name")
        .eq("stock_code", body.stock_code)
        .maybe_single()
        .execute()
    )
    stock_name = stock_result.data["stock_name"] if stock_result.data else None

    # 6. 주문 데이터 생성
    order_data = {
        "account_id": body.account_id,
        "stock_code": body.stock_code,
        "stock_name": stock_name,
        "order_type": body.order_type.value,
        "side": body.order_side.value,
        "quantity": body.quantity,
        "price": body.price,
        "filled_quantity": 0,
        "filled_price": None,
        "status": OrderStatus.PENDING.value,
    }

    result = sb.table("orders").insert(order_data).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="주문 생성에 실패했습니다.",
        )

    order = result.data[0]

    # 시장가 주문은 즉시 체결 시도
    if body.order_type == OrderType.MARKET:
        try:
            engine = get_trading_engine()
            fill_result = await engine.execute_order(order["id"])
            if fill_result["status"] == "filled":
                # 체결된 주문 데이터 다시 조회
                updated = sb.table("orders").select("*").eq("id", order["id"]).single().execute()
                order = updated.data
        except Exception as e:
            pass  # 체결 실패 시 pending 상태로 유지

    return OrderResponse(**order)


@router.get("", response_model=OrderListResponse)
async def list_orders(
    clerk_user_id: ClerkUserId,
    account_id: Optional[str] = Query(None, description="계좌 ID 필터"),
    order_status: Optional[OrderStatus] = Query(None, alias="status", description="상태 필터"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=200, description="페이지 크기"),
):
    """
    사용자의 주문 목록을 조회합니다.

    - account_id: 특정 계좌의 주문만 조회
    - status: 주문 상태별 필터링
    - 최신 주문 순으로 정렬
    """
    sb = get_supabase_client()

    # 먼저 사용자의 계좌 ID 목록을 조회
    if account_id:
        # 특정 계좌 → 소유권 확인
        acct_check = (
            sb.table("accounts")
            .select("id")
            .eq("id", account_id)
            .eq("clerk_user_id", clerk_user_id)
            .maybe_single()
            .execute()
        )
        if not acct_check.data:
            raise HTTPException(status_code=404, detail="계좌를 찾을 수 없습니다.")
        account_ids = [account_id]
    else:
        # 사용자의 모든 계좌
        accts = (
            sb.table("accounts")
            .select("id")
            .eq("clerk_user_id", clerk_user_id)
            .execute()
        )
        account_ids = [a["id"] for a in (accts.data or [])]
        if not account_ids:
            return OrderListResponse(items=[], total=0)

    query = (
        sb.table("orders")
        .select("*", count="exact")
        .in_("account_id", account_ids)
    )

    if order_status:
        query = query.eq("status", order_status.value)

    # 페이지네이션
    offset = (page - 1) * page_size
    query = query.range(offset, offset + page_size - 1)

    # 최신순 정렬
    query = query.order("created_at", desc=True)

    result = query.execute()

    items = [OrderResponse(**row) for row in (result.data or [])]
    total = result.count if result.count is not None else len(items)

    return OrderListResponse(items=items, total=total)


@router.delete("/{order_id}", response_model=OrderResponse)
async def cancel_order(
    order_id: str,
    clerk_user_id: ClerkUserId,
):
    """
    대기 중인 주문을 취소합니다.

    - pending 상태의 주문만 취소할 수 있습니다.
    - 이미 체결되었거나 취소된 주문은 취소할 수 없습니다.
    """
    sb = get_supabase_client()

    # 주문 조회
    order_result = (
        sb.table("orders")
        .select("*")
        .eq("id", order_id)
        .maybe_single()
        .execute()
    )

    if order_result.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없습니다.",
        )

    # 소유권 확인 (주문의 account_id → accounts.clerk_user_id)
    acct_check = (
        sb.table("accounts")
        .select("id")
        .eq("id", order_result.data["account_id"])
        .eq("clerk_user_id", clerk_user_id)
        .maybe_single()
        .execute()
    )
    if not acct_check.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문을 찾을 수 없거나 권한이 없습니다.",
        )

    order = order_result.data

    # 대기 상태가 아닌 주문은 취소 불가
    if order["status"] != OrderStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{order['status']}' 상태의 주문은 취소할 수 없습니다. "
                   f"대기(pending) 상태의 주문만 취소 가능합니다.",
        )

    # 상태를 cancelled로 변경
    update_result = (
        sb.table("orders")
        .update({
            "status": OrderStatus.CANCELLED.value,
            "cancelled_at": datetime.utcnow().isoformat(),
        })
        .eq("id", order_id)
        .execute()
    )

    if not update_result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="주문 취소에 실패했습니다.",
        )

    return OrderResponse(**update_result.data[0])
