"""
에이전트 라우트 — AI 에이전트 상태 조회 및 상호작용

에이전트 월드 상태, 대화 내역, 사용자 질문 등을 처리합니다.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.dependencies import ClerkUserId
from app.agents.agent_manager import get_agent_manager

router = APIRouter(prefix="/api/agents", tags=["agents"])


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


# ── 라우트 핸들러 ─────────────────────────────────────────────

@router.get("/world", response_model=WorldState)
async def get_world_state(clerk_user_id: ClerkUserId):
    """에이전트 월드 전체 상태를 조회합니다."""
    manager = get_agent_manager()
    return WorldState(**manager.get_world_state())


@router.get("/state/{agent_type}", response_model=AgentState)
async def get_agent_state(
    agent_type: str,
    clerk_user_id: ClerkUserId,
):
    """특정 에이전트의 상태를 조회합니다."""
    manager = get_agent_manager()
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
    manager = get_agent_manager()
    agent = manager.get_agent(body.agent_type)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"에이전트 '{body.agent_type}'를 찾을 수 없습니다.",
        )

    answer = await agent.respond_to_user(body.question)

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
    manager = get_agent_manager()
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
    manager = get_agent_manager()
    return {"ticks": manager.get_tick_history(limit)}


@router.post("/meeting")
async def trigger_meeting(
    clerk_user_id: ClerkUserId,
    topic: str = Query("사용자 요청 긴급 분석", description="미팅 주제"),
):
    """에이전트 긴급 미팅을 소집합니다."""
    manager = get_agent_manager()
    result = await manager.emergency_meeting(topic, trigger="user_request")
    return result


@router.get("/memory/{agent_type}")
async def get_agent_memories(
    agent_type: str,
    clerk_user_id: ClerkUserId,
    limit: int = Query(20, ge=1, le=100),
):
    """에이전트의 최근 메모리를 조회합니다."""
    manager = get_agent_manager()
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
    manager = get_agent_manager()
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
    manager = get_agent_manager()
    return await manager.get_agent_opinions(
        topic=body.topic,
        stock_code=body.stock_code,
    )
