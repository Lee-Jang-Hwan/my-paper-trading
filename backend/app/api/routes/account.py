"""
계좌 라우트 - 모의투자 계좌 관리

사용자별 가상 거래 계좌를 생성하고 조회합니다.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import ClerkUserId
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("account_route")

router = APIRouter(prefix="/api/account", tags=["account"])


# ── 요청/응답 모델 ───────────────────────────────────────────

class AccountResponse(BaseModel):
    """계좌 응답"""
    id: str
    clerk_user_id: str
    initial_capital: int
    balance: int
    total_asset: int
    pnl: Optional[int] = None          # 계산 필드: total_asset - initial_capital
    pnl_rate: Optional[float] = None   # 계산 필드: pnl / initial_capital * 100
    created_at: Optional[str] = None


class AccountCreateRequest(BaseModel):
    """계좌 생성 요청"""
    initial_capital: int = Field(
        default=10_000_000,
        ge=10_000_000,
        le=1_000_000_000,
        description="초기 투자금 (1천만원 ~ 10억원)",
    )


class HoldingResponse(BaseModel):
    """보유종목 응답"""
    id: str
    stock_code: str
    stock_name: str
    quantity: int
    avg_price: int
    current_price: int
    eval_amount: Optional[int] = None    # 평가금액: current_price * quantity
    pnl: Optional[int] = None            # 손익: eval_amount - (avg_price * quantity)
    pnl_rate: Optional[float] = None     # 수익률


class PortfolioResponse(BaseModel):
    """포트폴리오 응답"""
    account: AccountResponse
    holdings: list[HoldingResponse]


# ── 라우트 핸들러 ────────────────────────────────────────────

def _enrich_account(row: dict) -> dict:
    """계좌 데이터에 계산 필드 추가."""
    initial = row.get("initial_capital", 0)
    total = row.get("total_asset", 0)
    pnl = total - initial
    pnl_rate = (pnl / initial * 100) if initial > 0 else 0.0
    return {**row, "pnl": pnl, "pnl_rate": round(pnl_rate, 2)}


def _enrich_holding(row: dict) -> dict:
    """보유종목 데이터에 계산 필드 추가."""
    qty = row.get("quantity", 0)
    avg = row.get("avg_price", 0)
    cur = row.get("current_price", 0)
    eval_amount = cur * qty
    cost = avg * qty
    pnl = eval_amount - cost
    pnl_rate = (pnl / cost * 100) if cost > 0 else 0.0
    return {**row, "eval_amount": eval_amount, "pnl": pnl, "pnl_rate": round(pnl_rate, 2)}


@router.get("", response_model=list[AccountResponse])
async def get_accounts(clerk_user_id: ClerkUserId):
    """현재 사용자의 모든 모의투자 계좌를 조회합니다."""
    sb = get_supabase_client()
    try:
        result = (
            sb.table("accounts")
            .select("*")
            .eq("clerk_user_id", clerk_user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        logger.error(f"계좌 목록 조회 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="계좌 정보를 불러올 수 없습니다.",
        )
    return [AccountResponse(**_enrich_account(row)) for row in (result.data or [])]


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    body: AccountCreateRequest,
    clerk_user_id: ClerkUserId,
):
    """새 모의투자 계좌를 생성합니다."""
    sb = get_supabase_client()
    initial_capital = body.initial_capital

    try:
        # user_profiles에 사용자가 없으면 생성
        sb.table("user_profiles").upsert(
            {"clerk_user_id": clerk_user_id},
            on_conflict="clerk_user_id",
        ).execute()

        result = sb.table("accounts").insert({
            "clerk_user_id": clerk_user_id,
            "initial_capital": initial_capital,
            "balance": initial_capital,
            "total_asset": initial_capital,
        }).execute()
    except Exception as e:
        logger.error(f"계좌 생성 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="계좌 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="계좌 생성에 실패했습니다.",
        )

    return AccountResponse(**_enrich_account(result.data[0]))


@router.get("/portfolio/{account_id}", response_model=PortfolioResponse)
async def get_portfolio(
    account_id: str,
    clerk_user_id: ClerkUserId,
):
    """계좌의 포트폴리오 (계좌정보 + 보유종목)를 조회합니다. 실시간 가격으로 평가합니다."""
    sb = get_supabase_client()

    # 계좌 조회 + 소유권 확인
    try:
        acct_result = (
            sb.table("accounts")
            .select("*")
            .eq("id", account_id)
            .eq("clerk_user_id", clerk_user_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        logger.error(f"포트폴리오 계좌 조회 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="계좌 정보를 불러올 수 없습니다.",
        )

    if not acct_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="계좌를 찾을 수 없거나 권한이 없습니다.",
        )

    # 보유종목 조회
    try:
        holdings_result = (
            sb.table("holdings")
            .select("*")
            .eq("account_id", account_id)
            .order("stock_code")
            .execute()
        )
    except Exception as e:
        logger.error(f"보유종목 조회 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="보유종목 정보를 불러올 수 없습니다.",
        )

    holdings_raw = holdings_result.data or []

    # 실시간 가격으로 보유종목 평가 업데이트
    eval_total = 0
    try:
        from app.services.kis_api import get_kis_client
        kis = get_kis_client()

        # MarketDataService 캐시 우선 조회
        try:
            from app.services.market_data import get_market_data_service
            mds = get_market_data_service()
        except Exception as e:
            logger.debug(f"MarketDataService 초기화 실패, 캐시 없이 진행: {e}")
            mds = None

        for row in holdings_raw:
            stock_code = row.get("stock_code", "")
            live_price = None

            # 1) 캐시에서 조회
            if mds:
                try:
                    cached = await mds.get_price(stock_code)
                    if cached and cached.get("price", 0) > 0:
                        live_price = cached["price"]
                except Exception as e:
                    logger.debug(f"캐시 가격 조회 실패 ({stock_code}): {e}")

            # 2) KIS API 직접 호출
            if not live_price:
                try:
                    price_data = await kis.get_current_price(stock_code)
                    if price_data and price_data.get("price", 0) > 0:
                        live_price = price_data["price"]
                except Exception as e:
                    logger.debug(f"KIS 가격 조회 실패 ({stock_code}): {e}")

            # 실시간 가격이 있으면 교체
            if live_price:
                row["current_price"] = live_price

            eval_total += row.get("current_price", 0) * row.get("quantity", 0)
    except Exception as e:
        # 실시간 가격 조회 실패 시 기존 가격 유지
        logger.warning(f"실시간 가격 일괄 조회 실패, DB 가격 사용: {e}")
        for row in holdings_raw:
            eval_total += row.get("current_price", 0) * row.get("quantity", 0)

    # 계좌 총자산 재계산
    acct_data = acct_result.data
    acct_data["total_asset"] = acct_data.get("balance", 0) + eval_total

    account = AccountResponse(**_enrich_account(acct_data))
    holdings = [HoldingResponse(**_enrich_holding(row)) for row in holdings_raw]

    return PortfolioResponse(account=account, holdings=holdings)


@router.get("/transactions/{account_id}")
async def get_transactions(
    account_id: str,
    clerk_user_id: ClerkUserId,
    page: int = 1,
    page_size: int = 50,
):
    """계좌의 거래내역을 조회합니다."""
    sb = get_supabase_client()

    # 소유권 확인
    try:
        acct = (
            sb.table("accounts")
            .select("id")
            .eq("id", account_id)
            .eq("clerk_user_id", clerk_user_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        logger.error(f"거래내역 계좌 확인 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="계좌 정보를 불러올 수 없습니다.",
        )
    if not acct.data:
        raise HTTPException(status_code=404, detail="계좌를 찾을 수 없습니다.")

    offset = (page - 1) * page_size
    try:
        result = (
            sb.table("transactions")
            .select("*", count="exact")
            .eq("account_id", account_id)
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
    except Exception as e:
        logger.error(f"거래내역 조회 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="거래 내역을 불러올 수 없습니다.",
        )

    return {
        "items": result.data or [],
        "total": result.count or 0,
        "page": page,
        "page_size": page_size,
    }
