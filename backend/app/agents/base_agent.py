"""
Base Agent — Generative Agents 핵심 클래스

Stanford Generative Agents 아키텍처를 주식 트레이딩 도메인에 적용한
모든 에이전트의 기반 클래스입니다.

핵심 모듈:
1. Memory Stream — 관찰/대화/성찰/계획 기록 및 3축 검색
2. Reflection — 중요도 임계값 도달 시 고수준 통찰 생성
3. Planning — 일일/시간/실시간 3단계 계획
4. Behavior Loop — observe → retrieve → react → act (매 틱)
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, date, timezone
from enum import Enum
from typing import Any

from app.agents.memory_stream import MemoryStream
from app.db.supabase_client import get_supabase_client
from app.services.gemini_client import get_gemini_client

logger = logging.getLogger("base_agent")


class AgentAction(str, Enum):
    """에이전트 행동 유형."""
    IDLE = "idle"
    OBSERVE = "observe"       # 시장 관찰
    ANALYZE = "analyze"       # 분석 중
    TALK = "talk"             # 대화 중
    ALERT = "alert"           # 알림 전달
    WRITE = "write"           # 리포트 작성
    THINK = "think"           # 리플렉션/고민
    MOVE = "move"             # 이동 중
    EXCITED = "excited"       # 중요 발견


class AgentLocation(str, Enum):
    """에이전트 월드 맵 장소."""
    MARKET_BOARD = "market_board"       # 시장 전광판
    ANALYSIS_DESK = "analysis_desk"     # 분석 데스크
    NEWS_TERMINAL = "news_terminal"     # 뉴스 터미널
    PORTFOLIO_BOARD = "portfolio_board" # 포트폴리오 보드
    MEETING_TABLE = "meeting_table"     # 미팅 테이블
    USER_DESK = "user_desk"            # 사용자 데스크


class BaseAgent(ABC):
    """
    모든 AI 에이전트의 기반 클래스.

    서브클래스가 구현해야 하는 메서드:
    - perceive(): 현재 상황 관찰
    - analyze(): 전문 분석 수행
    - get_persona_prompt(): 페르소나 시스템 프롬프트
    """

    def __init__(
        self,
        agent_type: str,
        name: str,
        home_location: AgentLocation,
        llm_client=None,
    ):
        self.agent_type = agent_type
        self.name = name
        self.home_location = home_location

        # 코어 모듈
        self.memory = MemoryStream(agent_type)
        self._gemini = llm_client or get_gemini_client()
        self._sb = get_supabase_client()

        # 상태
        self.current_location = home_location
        self.current_action = AgentAction.IDLE
        self.current_action_description = ""
        self._current_plan: list[dict] = []
        self._plan_index = 0
        self._last_plan_date: date | None = None

        # 대화 상태
        self.is_in_conversation = False
        self.conversation_partner: str | None = None

    # ── 페르소나 (서브클래스 구현) ──────────────────────────────

    @abstractmethod
    def get_persona_prompt(self) -> str:
        """에이전트 페르소나 시스템 프롬프트."""
        ...

    @abstractmethod
    async def perceive(self) -> list[str]:
        """
        현재 환경을 관찰하여 관찰 목록을 반환.
        각 관찰은 자연어 문자열.
        """
        ...

    @abstractmethod
    async def analyze(self, observations: list[str], memories: list[dict]) -> dict | None:
        """
        관찰과 기억을 바탕으로 전문 분석 수행.
        분석 결과 dict 또는 None (분석할 것 없음).
        """
        ...

    # ── 행동 루프 (매 틱) ──────────────────────────────────────

    async def tick(self) -> dict[str, Any]:
        """
        에이전트 행동 루프 — 매 틱(~10-30초)마다 실행.

        1. PERCEIVE: 환경 관찰
        2. RETRIEVE: 관련 기억 검색
        3. REACT: 반응 결정 (계획 수정 여부)
        4. ACT: 행동 실행
        5. MEMORY: 결과 기억 저장

        Returns:
            현재 에이전트 상태 dict
        """
        tick_result: dict[str, Any] = {
            "agent": self.agent_type,
            "name": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # 1. PERCEIVE — 환경 관찰
            self.current_action = AgentAction.OBSERVE
            observations = await self.perceive()

            if not observations:
                self.current_action = AgentAction.IDLE
                self.current_action_description = "대기 중"
                tick_result["action"] = "idle"
                return tick_result

            # 관찰 결과를 메모리에 저장
            for obs in observations[:5]:  # 틱당 최대 5개 관찰
                await self.memory.add_observation(obs)

            # 2. RETRIEVE — 관련 기억 검색
            combined_query = " ".join(observations[:3])
            memories = await self.memory.retrieve(combined_query, k=10)

            # 3. REACT — 반응 판단
            should_react = await self._should_react(observations, memories)

            if should_react:
                # 4. ACT — 분석/행동 수행
                self.current_action = AgentAction.ANALYZE
                self.current_action_description = "분석 중..."
                analysis = await self.analyze(observations, memories)

                if analysis:
                    tick_result["analysis"] = analysis
                    tick_result["action"] = "analyzed"

                    # 분석 결과를 메모리에 저장
                    summary = analysis.get("summary", str(analysis)[:200])
                    await self.memory.add_observation(
                        f"분석 완료: {summary}",
                        related_stocks=analysis.get("related_stocks"),
                    )
            else:
                tick_result["action"] = "continued_plan"

            # 5. 리플렉션 확인
            if self.memory.should_reflect():
                self.current_action = AgentAction.THINK
                self.current_action_description = "통찰을 정리하는 중..."
                reflections = await self._reflect()
                if reflections:
                    tick_result["reflections"] = reflections

            # 현재 상태 업데이트
            tick_result["location"] = self.current_location.value
            tick_result["action_type"] = self.current_action.value
            tick_result["action_description"] = self.current_action_description

        except Exception as e:
            logger.error(f"[{self.name}] 틱 오류: {e}", exc_info=True)
            tick_result["error"] = str(e)
            self.current_action = AgentAction.IDLE

        return tick_result

    # ── 반응 판단 ──────────────────────────────────────────────

    async def _should_react(self, observations: list[str], memories: list[dict]) -> bool:
        """관찰 내용에 반응해야 하는지 LLM으로 판단."""
        if not observations:
            return False

        # 간단한 규칙 기반 판단 (LLM 호출 최소화)
        for obs in observations:
            # 급등락, 속보, 이상 신호 등은 항상 반응
            urgent_keywords = ["급등", "급락", "속보", "서킷브레이커", "서프라이즈", "폭등", "폭락", "긴급"]
            if any(kw in obs for kw in urgent_keywords):
                return True

        # 현재 계획에 따라 행동 중이면 계속 진행
        current_plan = self._get_current_plan_item()
        if current_plan:
            return False  # 계획대로 진행

        # 계획이 없거나 애매한 경우 반응
        return True

    # ── 리플렉션 (고수준 통찰 생성) ────────────────────────────

    async def _reflect(self) -> list[str]:
        """
        축적된 메모리에서 고수준 통찰 생성.

        프로세스:
        1. 최근 100개 메모리에서 핵심 질문 도출
        2. 각 질문에 대해 관련 메모리 검색
        3. 통찰 생성 후 메모리 스트림에 저장
        """
        recent_memories = await self.memory.retrieve_recent(100)
        if len(recent_memories) < 5:
            return []

        # 최근 메모리 요약
        memory_texts = [m["content"] for m in recent_memories[:30]]
        memory_summary = "\n".join(f"- {t}" for t in memory_texts)

        # 핵심 질문 생성
        questions_prompt = f"""당신은 {self.name}입니다.

최근 기억들:
{memory_summary}

위 기억들을 바탕으로, 지금 가장 중요하게 생각해봐야 할 질문 2개를 생성하세요.
주식시장 분석과 투자 판단에 도움이 되는 질문이어야 합니다.

JSON 배열로 답하세요: ["질문1", "질문2"]"""

        questions_result = await self._gemini.generate_json(
            questions_prompt,
            system_instruction=self.get_persona_prompt(),
        )

        if not questions_result or not isinstance(questions_result, list):
            self.memory.reset_reflection_accumulator()
            return []

        reflections = []
        for question in questions_result[:2]:
            # 질문과 관련된 메모리 검색
            relevant = await self.memory.retrieve(question, k=15)
            relevant_texts = [m["content"] for m in relevant]

            # 통찰 생성
            insight_prompt = f"""당신은 {self.name}입니다.

질문: {question}

관련 기억들:
{chr(10).join(f'- {t}' for t in relevant_texts)}

위 기억들을 종합하여 이 질문에 대한 핵심 통찰을 2-3문장으로 작성하세요.
구체적인 수치와 근거를 포함하세요."""

            insight = await self._gemini.generate(
                insight_prompt,
                system_instruction=self.get_persona_prompt(),
                tier="high",
                max_tokens=300,
            )

            if insight and not insight.startswith("["):
                reflections.append(insight)
                await self.memory.add_reflection(
                    f"[통찰] {question}\n→ {insight}",
                    related_stocks=self._extract_stock_codes(insight),
                )

        self.memory.reset_reflection_accumulator()
        logger.info(f"[{self.name}] 리플렉션 완료: {len(reflections)}개 통찰 생성")
        return reflections

    # ── 계획 (Planning) ────────────────────────────────────────

    async def create_daily_plan(self) -> list[dict]:
        """
        장 시작 전 일일 계획 생성.

        Returns:
            시간별 행동 계획 리스트: [{"time": "09:00", "action": "...", "duration": 30}, ...]
        """
        today = date.today()
        if self._last_plan_date == today and self._current_plan:
            return self._current_plan

        # 최근 기억 기반 컨텍스트
        recent = await self.memory.retrieve_recent(20)
        context = "\n".join(f"- {m['content']}" for m in recent[:10])

        plan_prompt = f"""당신은 {self.name}입니다. 오늘({today.isoformat()}) 일일 계획을 세우세요.

최근 기억:
{context}

한국 주식시장 운영 시간: 09:00 ~ 15:30
프리마켓 분석: 08:30 ~ 09:00
애프터마켓 정리: 15:30 ~ 16:00

JSON 배열로 답하세요:
[
  {{"time": "08:30", "action": "프리마켓 분석 설명", "duration_minutes": 30}},
  {{"time": "09:00", "action": "행동 설명", "duration_minutes": 30}},
  ...
]

{self.name}의 전문 영역에 맞는 구체적인 계획을 세우세요."""

        plan = await self._gemini.generate_json(
            plan_prompt,
            system_instruction=self.get_persona_prompt(),
        )

        if plan and isinstance(plan, list):
            self._current_plan = plan
            self._plan_index = 0
            self._last_plan_date = today

            # 계획을 DB에 저장
            try:
                self._sb.table("agent_plans").insert({
                    "agent_type": self.agent_type,
                    "plan_date": today.isoformat(),
                    "plan_json": plan,
                    "status": "active",
                }).execute()
            except Exception as e:
                logger.debug(f"계획 저장 실패: {e}")

            # 계획을 메모리에 저장
            plan_summary = ", ".join(f"{p.get('time')}: {p.get('action')}" for p in plan[:5])
            await self.memory.add_plan(f"오늘의 계획: {plan_summary}")

            logger.info(f"[{self.name}] 일일 계획 생성: {len(plan)}개 항목")
        else:
            self._current_plan = self._get_default_plan()

        return self._current_plan

    def _get_current_plan_item(self) -> dict | None:
        """현재 시간에 해당하는 계획 항목 반환."""
        if not self._current_plan:
            return None

        now = datetime.now()
        current_time = now.strftime("%H:%M")

        for i, item in enumerate(self._current_plan):
            item_time = item.get("time", "")
            if item_time <= current_time:
                if i + 1 < len(self._current_plan):
                    next_time = self._current_plan[i + 1].get("time", "23:59")
                    if current_time < next_time:
                        return item
                else:
                    return item
        return None

    def _get_default_plan(self) -> list[dict]:
        """기본 일일 계획."""
        return [
            {"time": "08:30", "action": "프리마켓 분석", "duration_minutes": 30},
            {"time": "09:00", "action": "장 초반 동향 파악", "duration_minutes": 30},
            {"time": "09:30", "action": "심층 분석", "duration_minutes": 120},
            {"time": "11:30", "action": "오전장 요약", "duration_minutes": 60},
            {"time": "12:30", "action": "오후장 모니터링", "duration_minutes": 90},
            {"time": "14:00", "action": "종합 분석", "duration_minutes": 80},
            {"time": "15:20", "action": "장 마감 리뷰", "duration_minutes": 40},
        ]

    # ── 대화 관련 ──────────────────────────────────────────────

    async def decide_conversation_target(self, topic: str) -> str | None:
        """주어진 주제에 대해 대화할 에이전트를 결정."""
        prompt = f"""당신은 {self.name}입니다.

다음 주제에 대해 다른 에이전트와 대화가 필요한지 판단하세요:
주제: {topic}

에이전트 목록:
- trend (한눈이): 시장 전체 동향, 섹터 분석, 수급 분석
- advisor (슬기): 개별 종목 분석, 기술적/기본적 분석, 매수매도 추천
- news (번개): 뉴스/속보 모니터링, 감성 분석
- portfolio (밸런스): 포트폴리오 관리, 리스크 최적화

당신({self.agent_type})을 제외하고, 이 주제에 대해 가장 적합한 대화 상대의 agent_type을 하나만 답하세요.
대화가 불필요하면 "none"이라고 답하세요.
agent_type만 답하세요 (trend/advisor/news/portfolio/none):"""

        result = await self._gemini.generate(
            prompt,
            system_instruction=self.get_persona_prompt(),
            tier="low",
            temperature=0.3,
            max_tokens=20,
        )

        target = result.strip().lower().split()[0] if result else "none"
        valid_targets = {"trend", "advisor", "news", "portfolio"}
        valid_targets.discard(self.agent_type)

        return target if target in valid_targets else None

    async def generate_utterance(
        self,
        conversation_history: list[dict],
        topic: str,
        partner_name: str,
    ) -> str:
        """대화에서 한 턴의 발화 생성."""
        history_text = "\n".join(
            f"{msg['speaker']}: {msg['content']}"
            for msg in conversation_history[-6:]  # 최근 6턴
        )

        # 관련 기억 검색
        relevant = await self.memory.retrieve(topic, k=5)
        memory_text = "\n".join(f"- {m['content']}" for m in relevant)

        prompt = f"""당신은 {self.name}입니다. {partner_name}와(과) 대화 중입니다.

주제: {topic}

관련 기억:
{memory_text}

대화 내용:
{history_text}

{self.name}으로서 자연스럽게 응답하세요. 2-3문장으로 간결하게 답하세요.
구체적인 수치나 근거를 포함하면 좋습니다."""

        return await self._gemini.generate(
            prompt,
            system_instruction=self.get_persona_prompt(),
            tier="high",
            max_tokens=200,
        )

    # ── 사용자 응답 ────────────────────────────────────────────

    async def respond_to_user(self, question: str, account_context: str | None = None) -> str:
        """사용자 질문에 응답."""
        # 관련 기억 검색
        memories = await self.memory.retrieve(question, k=15)
        memory_text = "\n".join(f"- {m['content']}" for m in memories)

        # 계좌 컨텍스트 섹션
        account_section = ""
        if account_context:
            account_section = f"""
{account_context}

위 계좌 정보를 참고하여 사용자의 실제 보유종목과 자산 상태를 기반으로 답변하세요.
"""

        prompt = f"""당신은 {self.name}입니다. 사용자가 질문했습니다.

질문: {question}
{account_section}
관련 기억/분석:
{memory_text}

전문가로서 사용자의 질문에 답변하세요.
구체적인 수치와 근거를 포함하되, 이해하기 쉽게 설명하세요.
투자 결정은 사용자가 내리도록 하되, 전문적인 의견을 제시하세요."""

        response = await self._gemini.generate(
            prompt,
            system_instruction=self.get_persona_prompt(),
            tier="high",
            max_tokens=500,
        )

        # 응답을 대화 메모리에 저장
        await self.memory.add_conversation(
            f"사용자 질문: {question}\n내 답변: {response[:200]}"
        )

        return response

    # ── 상태 조회 ──────────────────────────────────────────────

    def get_state(self) -> dict:
        """현재 에이전트 상태."""
        return {
            "agent_type": self.agent_type,
            "name": self.name,
            "location": self.current_location.value,
            "action": self.current_action.value,
            "action_description": self.current_action_description,
            "is_in_conversation": self.is_in_conversation,
            "conversation_partner": self.conversation_partner,
        }

    # ── 유틸리티 ───────────────────────────────────────────────

    @staticmethod
    def _extract_stock_codes(text: str) -> list[str]:
        """텍스트에서 6자리 종목코드 추출."""
        import re
        return re.findall(r"\b\d{6}\b", text)
