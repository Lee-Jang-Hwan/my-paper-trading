"""
에이전트 라우트 — AI 에이전트 상태 조회 및 상호작용

에이전트 월드 상태, 대화 내역, 사용자 질문 등을 처리합니다.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.dependencies import ClerkUserId
from app.agents.agent_manager import get_agent_manager
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("agents_route")

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ── 계좌 컨텍스트 빌더 ──────────────────────────────────────────

async def _build_account_context(clerk_user_id: str) -> str:
    """
    사용자의 실시간 계좌/보유종목 정보를 자연어 문자열로 포맷.

    에이전트가 사용자의 계좌 상태를 인식할 수 있도록
    잔고, 총자산, 수익률, 보유종목 상세를 포함합니다.
    """
    try:
        sb = get_supabase_client()

        # 1. 계좌 조회
        acct_result = (
            sb.table("accounts")
            .select("id, balance, total_asset, initial_capital")
            .eq("clerk_user_id", clerk_user_id)
            .limit(1)
            .execute()
        )

        if not acct_result.data:
            return ""

        acct = acct_result.data[0]
        account_id = acct["id"]
        balance = acct["balance"]
        total_asset = acct["total_asset"]
        initial_capital = acct["initial_capital"]

        # 수익률 계산
        if initial_capital and initial_capital > 0:
            profit_rate = (total_asset - initial_capital) / initial_capital * 100
            profit_sign = "+" if profit_rate >= 0 else ""
            profit_str = f"{profit_sign}{profit_rate:.1f}%"
        else:
            profit_str = "N/A"

        # 2. 보유종목 조회
        hold_result = (
            sb.table("holdings")
            .select("stock_code, stock_name, quantity, avg_price, current_price")
            .eq("account_id", account_id)
            .gt("quantity", 0)
            .execute()
        )

        holdings = hold_result.data or []

        # 3. 자연어 포맷
        lines = [
            f"[사용자 계좌 현황]",
            f"- 초기자본: {initial_capital:,}원",
            f"- 현금 잔고: {balance:,}원",
            f"- 총 자산: {total_asset:,}원",
            f"- 총 수익률: {profit_str}",
        ]

        if holdings:
            lines.append(f"- 보유종목 ({len(holdings)}개):")
            for h in holdings:
                qty = h["quantity"]
                avg = h["avg_price"]
                cur = h["current_price"] or avg
                eval_amt = qty * cur
                if avg and avg > 0:
                    pnl_rate = (cur - avg) / avg * 100
                    pnl_sign = "+" if pnl_rate >= 0 else ""
                    pnl_str = f"{pnl_sign}{pnl_rate:.1f}%"
                else:
                    pnl_str = "N/A"
                lines.append(
                    f"  · {h['stock_name']}({h['stock_code']}) "
                    f"{qty}주, 평단 {avg:,}원, 현재가 {cur:,}원, "
                    f"평가금액 {eval_amt:,}원, 수익률 {pnl_str}"
                )
        else:
            lines.append("- 보유종목: 없음")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"계좌 컨텍스트 빌드 실패: {e}")
        return ""


# ── 응답 모델 ─────────────────────────────────────────────────

class AgentState(BaseModel):
    """에이전트 상태."""
    agent_type: str
    name: str
    location: str
    action: str
    action_description: str
    is_in_conversation: bool
    conversation_partner: Optional[str] = None


class WorldState(BaseModel):
    """에이전트 월드 상태."""
    tick_count: int
    running: bool
    agents: list[AgentState]
    recent_conversations: list[dict]
    gemini_status: dict


class ConversationMessage(BaseModel):
    """대화 메시지."""
    turn: int
    speaker: str
    speaker_type: str
    content: str
    timestamp: str


class ConversationResponse(BaseModel):
    """대화 응답."""
    initiator: Optional[str] = None
    target: Optional[str] = None
    topic: str
    messages: list[dict]
    conclusion: Optional[str] = None


class UserQuestionRequest(BaseModel):
    """사용자 질문 요청."""
    agent_type: str = Field(..., description="질문할 에이전트: trend/advisor/news/portfolio")
    question: str = Field(..., min_length=2, max_length=500, description="질문 내용")


class UserQuestionResponse(BaseModel):
    """사용자 질문 응답."""
    agent_type: str
    agent_name: str
    question: str
    answer: str


class DebateRequest(BaseModel):
    """토론 시작 요청."""
    topic: str = Field(..., min_length=2, max_length=200, description="토론 주제")
    stock_code: Optional[str] = Field(None, description="관련 종목코드")
    stock_name: Optional[str] = Field(None, description="관련 종목명")


class OpinionRequest(BaseModel):
    """의견 조회 요청."""
    topic: str = Field(..., min_length=2, max_length=200, description="주제")
    stock_code: Optional[str] = Field(None, description="관련 종목코드")


# ── 헬퍼 ─────────────────────────────────────────────────────

def _require_manager():
    """agent_manager가 준비되지 않으면 503을 반환합니다."""
    manager = _require_manager()
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI 에이전트 시스템이 아직 초기화되지 않았습니다. 잠시 후 다시 시도해주세요.",
        )
    return manager


# ── 라우트 핸들러 ─────────────────────────────────────────────

@router.get("/world", response_model=WorldState)
async def get_world_state(clerk_user_id: ClerkUserId):
    """에이전트 월드 전체 상태를 조회합니다."""
    manager = _require_manager()
    return WorldState(**manager.get_world_state())


@router.get("/state/{agent_type}", response_model=AgentState)
async def get_agent_state(
    agent_type: str,
    clerk_user_id: ClerkUserId,
):
    """특정 에이전트의 상태를 조회합니다."""
    manager = _require_manager()
    agent = manager.get_agent(agent_type)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{agent_type}'를 찾을 수 없습니다. "
                   f"사용 가능: trend, advisor, news, portfolio",
        )
    return AgentState(**agent.get_state())


@router.post("/ask", response_model=UserQuestionResponse)
async def ask_agent(
    body: UserQuestionRequest,
    clerk_user_id: ClerkUserId,
):
    """에이전트에게 질문합니다."""
    manager = _require_manager()
    agent = manager.get_agent(body.agent_type)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{body.agent_type}'를 찾을 수 없습니다.",
        )

    account_context = await _build_account_context(clerk_user_id)
    answer = await agent.respond_to_user(body.question, account_context=account_context)

    return UserQuestionResponse(
        agent_type=body.agent_type,
        agent_name=agent.name,
        question=body.question,
        answer=answer,
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def get_recent_conversations(
    clerk_user_id: ClerkUserId,
    limit: int = Query(10, ge=1, le=50, description="조회 개수"),
):
    """최근 에이전트 간 대화 내역을 조회합니다."""
    manager = _require_manager()
    convos = manager.conversation.get_recent_conversations(limit)
    return [ConversationResponse(**c) for c in convos]


@router.get("/conversations/history")
async def get_conversation_history(
    clerk_user_id: ClerkUserId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """DB에서 대화 이력을 조회합니다."""
    from app.db.supabase_client import get_supabase_client
    sb = get_supabase_client()

    offset = (page - 1) * page_size
    result = (
        sb.table("agent_conversations")
        .select("*", count="exact")
        .order("created_at", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )

    return {
        "items": result.data or [],
        "total": result.count or 0,
        "page": page,
        "page_size": page_size,
    }


@router.get("/ticks")
async def get_tick_history(
    clerk_user_id: ClerkUserId,
    limit: int = Query(20, ge=1, le=100),
):
    """최근 틱 실행 이력을 조회합니다."""
    manager = _require_manager()
    return {"ticks": manager.get_tick_history(limit)}


@router.post("/meeting")
async def trigger_meeting(
    clerk_user_id: ClerkUserId,
    topic: str = Query("사용자 요청 긴급 분석", description="미팅 주제"),
):
    """에이전트 긴급 미팅을 소집합니다."""
    manager = _require_manager()
    result = await manager.emergency_meeting(topic, trigger="user_request")
    return result


@router.get("/memory/{agent_type}")
async def get_agent_memories(
    agent_type: str,
    clerk_user_id: ClerkUserId,
    limit: int = Query(20, ge=1, le=100),
):
    """에이전트의 최근 메모리를 조회합니다."""
    manager = _require_manager()
    agent = manager.get_agent(agent_type)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{agent_type}'를 찾을 수 없습니다.",
        )

    memories = await agent.memory.retrieve_recent(limit)
    stats = await agent.memory.get_stats()

    return {
        "agent_type": agent_type,
        "stats": stats,
        "memories": [
            {
                "id": m["id"],
                "memory_type": m["memory_type"],
                "content": m["content"],
                "importance_score": m["importance_score"],
                "created_at": m["created_at"],
            }
            for m in memories
        ],
    }


@router.post("/debate")
async def start_debate(
    body: DebateRequest,
    clerk_user_id: ClerkUserId,
):
    """
    에이전트 토론을 시작합니다.

    토론은 백그라운드로 진행되며, conversation_id를 즉시 반환합니다.
    WebSocket /ws/agents를 통해 실시간으로 턴 메시지를 수신할 수 있습니다.
    """
    manager = _require_manager()
    result = await manager.start_debate(
        topic=body.topic,
        stock_code=body.stock_code,
        stock_name=body.stock_name,
    )

    if result.get("status") == "cooldown":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result["message"],
        )

    if result.get("status") == "busy":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result["message"],
        )

    if result.get("status") == "unavailable":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=result["message"],
        )

    return result


@router.post("/opinions")
async def get_opinions(
    body: OpinionRequest,
    clerk_user_id: ClerkUserId,
):
    """
    4개 에이전트의 의견을 동시에 조회합니다.

    각 에이전트가 주제에 대한 의견, 감성(bullish/bearish/neutral),
    신뢰도, 핵심 포인트를 제공하며, 전체 합의도를 함께 반환합니다.
    """
    manager = _require_manager()
    account_context = await _build_account_context(clerk_user_id)
    return await manager.get_agent_opinions(
        topic=body.topic,
        stock_code=body.stock_code,
        account_context=account_context,
    )
