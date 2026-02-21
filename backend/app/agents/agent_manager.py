"""
에이전트 오케스트레이터 (Agent Manager)

모든 에이전트의 라이프사이클을 관리합니다:
- 틱 기반 행동 루프 실행
- 정기 미팅 스케줄링
- 긴급 소집
- 에이전트 간 정보 확산
- 월드 상태 관리
"""

import asyncio
import logging
import uuid
from datetime import datetime, time, timezone, timedelta
from typing import Any, Callable, Awaitable

from app.agents.base_agent import AgentAction, AgentLocation
from app.agents.trend_agent import TrendAgent
from app.agents.advisor_agent import AdvisorAgent
from app.agents.news_agent import NewsAgent
from app.agents.portfolio_agent import PortfolioAgent
from app.agents.conversation import ConversationManager
from app.config import get_settings
from app.services.gemini_client import get_gemini_client
from app.services.openai_client import get_openai_client

logger = logging.getLogger("agent_manager")

# 정기 미팅 시간 (KST)
MEETING_SCHEDULE = {
    "morning": time(8, 45),    # 장 시작 전 브리핑
    "midday": time(12, 0),     # 점심 중간 점검
    "closing": time(15, 25),   # 장 마감 리뷰
}


class AgentManager:
    """에이전트 오케스트레이터."""

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._running = False
        self._tick_task: asyncio.Task | None = None

        # 에이전트 인스턴스
        # trend, portfolio → Gemini  /  advisor, news → OpenAI
        openai_llm = get_openai_client()
        self.trend = TrendAgent()
        self.advisor = AdvisorAgent(llm_client=openai_llm)
        self.news = NewsAgent(llm_client=openai_llm)
        self.portfolio = PortfolioAgent()

        # Redis 연결
        for agent in self.agents:
            agent.set_redis(redis_client)

        # 대화 관리자
        self.conversation = ConversationManager()

        # 상태
        self._tick_count = 0
        self._last_meeting: dict[str, str] = {}  # meeting_type -> last_date
        self._tick_history: list[dict] = []

        # 토론 상태
        self._active_debate_id: str | None = None
        self._last_debate_time: datetime | None = None
        self._debate_cooldown = 60  # 초

    @property
    def agents(self) -> list:
        return [self.trend, self.advisor, self.news, self.portfolio]

    def get_agent(self, agent_type: str):
        """agent_type으로 에이전트 조회."""
        mapping = {
            "trend": self.trend,
            "advisor": self.advisor,
            "news": self.news,
            "portfolio": self.portfolio,
        }
        return mapping.get(agent_type)

    # ── 라이프사이클 ───────────────────────────────────────────

    async def start(self) -> None:
        """에이전트 시스템 시작."""
        self._running = True
        settings = get_settings()
        tick_interval = settings.AGENT_TICK_INTERVAL

        # 일일 계획 생성
        for agent in self.agents:
            try:
                await agent.create_daily_plan()
            except Exception as e:
                logger.warning(f"[{agent.name}] 일일 계획 생성 실패: {e}")

        # 틱 루프 시작
        self._tick_task = asyncio.create_task(self._tick_loop(tick_interval))
        logger.info(f"에이전트 시스템 시작 (틱 간격: {tick_interval}초)")

    async def stop(self) -> None:
        """에이전트 시스템 종료."""
        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        logger.info("에이전트 시스템 종료")

    # ── 틱 루프 ────────────────────────────────────────────────

    async def _tick_loop(self, interval: int) -> None:
        """메인 틱 루프."""
        while self._running:
            try:
                await asyncio.sleep(interval)
                self._tick_count += 1

                # 정기 미팅 체크
                await self._check_meetings()

                # 각 에이전트 틱 실행 (병렬)
                results = await asyncio.gather(
                    *[self._safe_tick(agent) for agent in self.agents],
                    return_exceptions=True,
                )

                tick_result = {
                    "tick": self._tick_count,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "agents": [],
                }

                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"[{self.agents[i].name}] 틱 오류: {result}")
                        tick_result["agents"].append({
                            "agent": self.agents[i].agent_type,
                            "error": str(result),
                        })
                    else:
                        tick_result["agents"].append(result)

                        # 대화 트리거 확인
                        if isinstance(result, dict) and result.get("analysis"):
                            await self._check_conversation_triggers(
                                self.agents[i], result
                            )

                # 틱 이력 저장
                self._tick_history.append(tick_result)
                if len(self._tick_history) > 100:
                    self._tick_history = self._tick_history[-100:]

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"틱 루프 오류: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _safe_tick(self, agent) -> dict:
        """에이전트 틱 실행 (예외 안전)."""
        try:
            return await agent.tick()
        except Exception as e:
            return {"agent": agent.agent_type, "error": str(e)}

    # ── 대화 트리거 ────────────────────────────────────────────

    async def _check_conversation_triggers(self, agent, tick_result: dict) -> None:
        """틱 결과에 따라 에이전트 간 대화를 트리거."""
        analysis = tick_result.get("analysis", {})

        # 1. 긴급 뉴스 → 다른 에이전트에게 전파
        if analysis.get("urgent"):
            notify_list = analysis.get("notify_agents", [])
            for target_type in notify_list:
                target = self.get_agent(target_type)
                if target and not target.is_in_conversation:
                    await self.conversation.start_conversation(
                        agent, target,
                        topic=analysis.get("summary", "긴급 분석"),
                        trigger_event="urgent_news",
                    )
                    break  # 한 틱에 하나의 대화만

        # 2. 높은 리스크 감지 → 관련 에이전트와 토론
        if analysis.get("risk_level") == "high":
            target_type = await agent.decide_conversation_target(
                analysis.get("summary", "리스크 분석")
            )
            if target_type:
                target = self.get_agent(target_type)
                if target and not target.is_in_conversation:
                    await self.conversation.start_conversation(
                        agent, target,
                        topic=analysis.get("summary", "리스크 토론"),
                        trigger_event="high_risk",
                    )

    # ── 정기 미팅 ──────────────────────────────────────────────

    async def _check_meetings(self) -> None:
        """정기 미팅 시간 확인 및 실행."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        current_time = now.time()

        for meeting_type, scheduled_time in MEETING_SCHEDULE.items():
            # 오늘 이미 진행했으면 스킵
            if self._last_meeting.get(meeting_type) == today:
                continue

            # 예정 시간 ± 2분 이내
            scheduled_dt = datetime.combine(now.date(), scheduled_time)
            diff = abs((now - scheduled_dt).total_seconds())

            if diff <= 120:  # 2분 이내
                self._last_meeting[meeting_type] = today

                topic_map = {
                    "morning": "오늘 장 시작 전 시장 전망 및 전략 논의",
                    "midday": "오전장 중간 점검 및 오후 전략",
                    "closing": "오늘 장 마감 리뷰 및 내일 전망",
                }

                # 대화 중이 아닌 에이전트만 참가
                participants = [a for a in self.agents if not a.is_in_conversation]
                if len(participants) >= 2:
                    try:
                        # 에이전트를 미팅 테이블로 이동
                        for agent in participants:
                            agent.current_location = AgentLocation.MEETING_TABLE
                            agent.current_action = AgentAction.TALK

                        await self.conversation.start_meeting(
                            participants,
                            topic=topic_map.get(meeting_type, "정기 미팅"),
                            meeting_type=meeting_type,
                        )
                    finally:
                        # 원래 위치로 복귀
                        for agent in participants:
                            agent.current_location = agent.home_location
                            agent.current_action = AgentAction.IDLE

    # ── 긴급 소집 ──────────────────────────────────────────────

    async def emergency_meeting(self, topic: str, trigger: str = "emergency") -> dict:
        """긴급 에이전트 소집."""
        logger.info(f"긴급 소집: {topic}")

        participants = [a for a in self.agents if not a.is_in_conversation]
        for agent in participants:
            agent.current_location = AgentLocation.MEETING_TABLE
            agent.current_action = AgentAction.TALK

        try:
            result = await self.conversation.start_meeting(
                participants,
                topic=topic,
                meeting_type="emergency",
            )
        finally:
            for agent in participants:
                agent.current_location = agent.home_location
                agent.current_action = AgentAction.IDLE

        return result

    # ── 브로드캐스터 연결 ────────────────────────────────────────

    def set_broadcaster(self, callback: Callable[[dict], Any]):
        """WebSocket 브로드캐스터 설정."""
        self.conversation.set_broadcaster(callback)

    # ── 사용자 토론 요청 ──────────────────────────────────────────

    async def start_debate(
        self,
        topic: str,
        stock_code: str | None = None,
        stock_name: str | None = None,
    ) -> dict[str, Any]:
        """
        사용자 요청 토론을 백그라운드로 시작.
        conversation_id를 즉시 반환합니다.
        """
        now = datetime.now(timezone.utc)

        # 쿨다운 체크
        if self._last_debate_time:
            elapsed = (now - self._last_debate_time).total_seconds()
            if elapsed < self._debate_cooldown:
                remaining = int(self._debate_cooldown - elapsed)
                return {
                    "status": "cooldown",
                    "remaining_seconds": remaining,
                    "message": f"{remaining}초 후에 다시 시도해주세요.",
                }

        # 동시 토론 제한
        if self._active_debate_id:
            return {
                "status": "busy",
                "conversation_id": self._active_debate_id,
                "message": "이미 진행 중인 토론이 있습니다.",
            }

        conv_id = str(uuid.uuid4())
        self._active_debate_id = conv_id
        self._last_debate_time = now

        full_topic = topic
        if stock_code:
            full_topic = f"{topic} (종목: {stock_name or stock_code})"

        participants = [a for a in self.agents if not a.is_in_conversation]
        if len(participants) < 2:
            self._active_debate_id = None
            return {
                "status": "unavailable",
                "message": "대화 가능한 에이전트가 부족합니다.",
            }

        # 백그라운드로 미팅 실행
        async def _run_debate():
            try:
                for agent in participants:
                    agent.current_location = AgentLocation.MEETING_TABLE
                    agent.current_action = AgentAction.TALK

                await self.conversation.start_meeting(
                    participants,
                    topic=full_topic,
                    meeting_type="user_debate",
                    conversation_id=conv_id,
                )
            except Exception as e:
                logger.error(f"토론 실행 오류: {e}", exc_info=True)
            finally:
                for agent in participants:
                    agent.current_location = agent.home_location
                    agent.current_action = AgentAction.IDLE
                self._active_debate_id = None

        asyncio.create_task(_run_debate())

        return {
            "status": "started",
            "conversation_id": conv_id,
            "topic": full_topic,
            "participants": [
                {"agent_type": a.agent_type, "name": a.name}
                for a in participants
            ],
        }

    async def get_agent_opinions(
        self,
        topic: str,
        stock_code: str | None = None,
        account_context: str | None = None,
    ) -> dict[str, Any]:
        """
        4개 에이전트에게 병렬로 의견을 요청합니다.
        """
        full_topic = topic
        if stock_code:
            full_topic = f"{topic} (종목코드: {stock_code})"

        # 계좌 컨텍스트 섹션
        account_section = ""
        if account_context:
            account_section = f"""
{account_context}

위 계좌 정보를 참고하여 사용자의 실제 보유종목과 자산 상태를 기반으로 의견을 제시하세요.
"""

        async def _get_opinion(agent) -> dict[str, Any]:
            """개별 에이전트 의견 생성."""
            memories = await agent.memory.retrieve(full_topic, k=10)
            memory_text = "\n".join(f"- {m['content']}" for m in memories)

            prompt = f"""당신은 {agent.name}입니다.

다음 주제에 대해 투자 전문가로서의 의견을 제시하세요:
주제: {full_topic}
{account_section}
관련 기억/분석:
{memory_text}

다음 JSON 형식으로 답하세요:
{{
  "opinion": "핵심 의견 (2-3문장)",
  "sentiment": "bullish 또는 bearish 또는 neutral",
  "confidence": 0.0~1.0 사이의 신뢰도,
  "key_points": ["핵심 포인트1", "핵심 포인트2", "핵심 포인트3"]
}}"""

            try:
                result = await agent._gemini.generate_json(
                    prompt,
                    system_instruction=agent.get_persona_prompt(),
                )
                if isinstance(result, dict):
                    return {
                        "agent_type": agent.agent_type,
                        "agent_name": agent.name,
                        **result,
                    }
            except Exception as e:
                logger.warning(f"[{agent.name}] 의견 생성 실패: {e}")

            return {
                "agent_type": agent.agent_type,
                "agent_name": agent.name,
                "opinion": "의견을 생성할 수 없습니다.",
                "sentiment": "neutral",
                "confidence": 0.0,
                "key_points": [],
            }

        # 4개 에이전트 병렬 실행
        opinions = await asyncio.gather(
            *[_get_opinion(agent) for agent in self.agents]
        )

        # 합의도 분석
        sentiments = [o.get("sentiment", "neutral") for o in opinions]
        bullish_count = sentiments.count("bullish")
        bearish_count = sentiments.count("bearish")
        total = len(sentiments)

        if bullish_count == total or bearish_count == total:
            agreement_level = "strong"
        elif bullish_count >= 3 or bearish_count >= 3:
            agreement_level = "moderate"
        elif bullish_count == 2 and bearish_count == 2:
            agreement_level = "divided"
        else:
            agreement_level = "mixed"

        # 합의 요약 생성
        opinions_text = "\n".join(
            f"- {o['agent_name']}({o['agent_type']}): {o.get('opinion', '')} [{o.get('sentiment', '')}]"
            for o in opinions
        )
        consensus_prompt = f"""주제: {full_topic}

에이전트별 의견:
{opinions_text}

위 의견들을 종합하여 1-2문장으로 합의 요약을 작성하세요.
어떤 점에서 의견이 일치하고, 어떤 점에서 다른지 포함하세요."""

        try:
            consensus = await get_gemini_client().generate(
                consensus_prompt, tier="medium", max_tokens=150
            )
        except Exception:
            consensus = "합의 요약을 생성할 수 없습니다."

        return {
            "topic": full_topic,
            "opinions": opinions,
            "consensus": consensus,
            "agreement_level": agreement_level,
        }

    # ── 상태 조회 ──────────────────────────────────────────────

    def get_world_state(self) -> dict:
        """전체 에이전트 월드 상태."""
        return {
            "tick_count": self._tick_count,
            "running": self._running,
            "agents": [agent.get_state() for agent in self.agents],
            "recent_conversations": self.conversation.get_recent_conversations(5),
            "gemini_status": {
                "available": self._gemini_available(),
                "tokens_used": self._gemini_tokens_used(),
            },
        }

    def get_tick_history(self, limit: int = 20) -> list[dict]:
        """최근 틱 이력."""
        return self._tick_history[-limit:]

    def _gemini_available(self) -> bool:
        from app.services.gemini_client import get_gemini_client
        return get_gemini_client().is_available

    def _gemini_tokens_used(self) -> int:
        from app.services.gemini_client import get_gemini_client
        return get_gemini_client().tokens_used_today


# ── 싱글턴 ────────────────────────────────────────────────────

_manager: AgentManager | None = None


def get_agent_manager(redis_client=None) -> AgentManager:
    global _manager
    if _manager is None:
        _manager = AgentManager(redis_client)
    return _manager
