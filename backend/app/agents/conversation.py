"""
에이전트 간 대화 시스템

에이전트들이 자율적으로 대화를 시작하고, 턴제 방식으로
의견을 교환하는 시스템입니다.

트리거 조건:
1. 근접성: 같은 영역에 있을 때
2. 관련성: 다른 에이전트의 전문 영역 관련 정보 발견
3. 긴급성: 속보/급등락 (강제 소집)
4. 주기적: 정기 미팅 시간
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from app.db.supabase_client import get_supabase_client
from app.services.gemini_client import get_gemini_client

logger = logging.getLogger("conversation")

MAX_CONVERSATION_TURNS = 6  # 최대 대화 턴 수

BroadcastCallback = Callable[[dict[str, Any]], Awaitable[None]]


class ConversationManager:
    """에이전트 간 대화 관리."""

    def __init__(self):
        self._sb = get_supabase_client()
        self._gemini = get_gemini_client()
        self._active_conversations: list[dict] = []
        self._broadcaster: BroadcastCallback | None = None

    def set_broadcaster(self, callback: BroadcastCallback):
        """실시간 브로드캐스트 콜백 설정."""
        self._broadcaster = callback

    async def _broadcast(self, event: dict[str, Any]):
        """브로드캐스터가 설정된 경우에만 이벤트 전송."""
        if self._broadcaster:
            try:
                await self._broadcaster(event)
            except Exception as e:
                logger.warning(f"브로드캐스트 실패: {e}")

    async def start_conversation(
        self,
        initiator,  # BaseAgent
        target,      # BaseAgent
        topic: str,
        trigger_event: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        두 에이전트 간 대화 시작 및 진행.

        Returns:
            대화 결과 dict (conversation_log, conclusion, etc.)
        """
        conv_id = conversation_id or str(uuid.uuid4())
        logger.info(
            f"대화 시작: {initiator.name} → {target.name}, 주제: {topic}, id: {conv_id}"
        )

        # 대화 상태 설정
        initiator.is_in_conversation = True
        initiator.conversation_partner = target.agent_type
        target.is_in_conversation = True
        target.conversation_partner = initiator.agent_type

        conversation_log: list[dict] = []

        # 대화 시작 브로드캐스트
        await self._broadcast({
            "type": "conversation_start",
            "conversation_id": conv_id,
            "data": {
                "initiator": initiator.agent_type,
                "initiator_name": initiator.name,
                "target": target.agent_type,
                "target_name": target.name,
                "topic": topic,
                "max_turns": MAX_CONVERSATION_TURNS,
            },
        })

        try:
            for turn in range(MAX_CONVERSATION_TURNS):
                if turn % 2 == 0:
                    # 시작자 턴
                    speaker = initiator
                    listener = target
                else:
                    # 대상자 턴
                    speaker = target
                    listener = initiator

                utterance = await speaker.generate_utterance(
                    conversation_log,
                    topic,
                    listener.name,
                )

                message = {
                    "turn": turn,
                    "speaker": speaker.name,
                    "speaker_type": speaker.agent_type,
                    "content": utterance,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                conversation_log.append(message)

                # 턴 메시지 브로드캐스트
                await self._broadcast({
                    "type": "turn_message",
                    "conversation_id": conv_id,
                    "data": message,
                })

                # 대화 종료 판단
                if turn >= 3:  # 최소 4턴 후 종료 가능
                    should_end = await self._should_end_conversation(conversation_log)
                    if should_end:
                        break

            # 대화 결론 도출
            conclusion = await self._summarize_conclusion(
                conversation_log, initiator.name, target.name, topic
            )

            # DB에 저장
            conversation_record = {
                "initiator_agent": initiator.agent_type,
                "target_agent": target.agent_type,
                "topic": topic,
                "conversation_json": conversation_log,
                "conclusion": conclusion,
                "trigger_event": trigger_event,
                "conversation_id": conv_id,
            }

            try:
                self._sb.table("agent_conversations").insert(conversation_record).execute()
            except Exception as e:
                logger.error(f"대화 저장 실패: {e}")

            # 양쪽 에이전트 메모리에 대화 내용 저장
            conv_summary = f"{initiator.name}와 {target.name}의 대화 ({topic}): {conclusion}"
            await initiator.memory.add_conversation(conv_summary)
            await target.memory.add_conversation(conv_summary)

            result = {
                "conversation_id": conv_id,
                "initiator": initiator.agent_type,
                "target": target.agent_type,
                "topic": topic,
                "messages": conversation_log,
                "conclusion": conclusion,
                "turn_count": len(conversation_log),
            }

            self._active_conversations.append(result)
            # 최근 20개만 유지
            if len(self._active_conversations) > 20:
                self._active_conversations = self._active_conversations[-20:]

            # 대화 종료 브로드캐스트
            await self._broadcast({
                "type": "conversation_end",
                "conversation_id": conv_id,
                "data": {
                    "conclusion": conclusion,
                    "turn_count": len(conversation_log),
                },
            })

            return result

        finally:
            # 대화 상태 해제
            initiator.is_in_conversation = False
            initiator.conversation_partner = None
            target.is_in_conversation = False
            target.conversation_partner = None

    async def start_meeting(
        self,
        agents: list,  # list[BaseAgent]
        topic: str,
        meeting_type: str = "regular",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        다수 에이전트 미팅 (장 시작 전, 점심, 장 마감 전).

        각 에이전트가 순서대로 발언하며, 마지막에 종합 결론을 도출합니다.
        """
        conv_id = conversation_id or str(uuid.uuid4())
        logger.info(f"미팅 시작: {meeting_type}, 참가: {[a.name for a in agents]}, id: {conv_id}")

        conversation_log: list[dict] = []

        # 미팅 시작 브로드캐스트
        await self._broadcast({
            "type": "meeting_start",
            "conversation_id": conv_id,
            "data": {
                "meeting_type": meeting_type,
                "topic": topic,
                "participants": [
                    {"agent_type": a.agent_type, "name": a.name}
                    for a in agents
                ],
                "total_rounds": 2,
            },
        })

        # 각 에이전트가 1-2회 발언
        for round_num in range(2):
            for agent in agents:
                utterance = await agent.generate_utterance(
                    conversation_log,
                    topic,
                    "전체 에이전트",
                )

                message = {
                    "turn": len(conversation_log),
                    "speaker": agent.name,
                    "speaker_type": agent.agent_type,
                    "content": utterance,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "round": round_num + 1,
                }
                conversation_log.append(message)

                # 턴 메시지 브로드캐스트
                await self._broadcast({
                    "type": "turn_message",
                    "conversation_id": conv_id,
                    "data": message,
                })

        # 종합 결론 도출
        conclusion = await self._summarize_meeting(conversation_log, topic, meeting_type)

        # DB 저장
        meeting_record = {
            "initiator_agent": "system",
            "target_agent": "all",
            "topic": f"[{meeting_type}] {topic}",
            "conversation_json": conversation_log,
            "conclusion": conclusion,
            "trigger_event": meeting_type,
            "conversation_id": conv_id,
        }

        try:
            self._sb.table("agent_conversations").insert(meeting_record).execute()
        except Exception:
            pass

        # 모든 에이전트 메모리에 미팅 결과 저장
        meeting_summary = f"[{meeting_type} 미팅] {topic}: {conclusion}"
        for agent in agents:
            await agent.memory.add_conversation(meeting_summary)

        result = {
            "conversation_id": conv_id,
            "meeting_type": meeting_type,
            "topic": topic,
            "participants": [a.agent_type for a in agents],
            "messages": conversation_log,
            "conclusion": conclusion,
        }

        self._active_conversations.append(result)

        # 미팅 종료 브로드캐스트
        await self._broadcast({
            "type": "meeting_end",
            "conversation_id": conv_id,
            "data": {
                "conclusion": conclusion,
                "turn_count": len(conversation_log),
            },
        })

        return result

    async def _should_end_conversation(self, log: list[dict]) -> bool:
        """대화 종료 여부 판단."""
        if len(log) >= MAX_CONVERSATION_TURNS:
            return True

        # 마지막 2개 메시지에 합의/결론 키워드가 있으면 종료
        recent = " ".join(msg["content"] for msg in log[-2:])
        end_keywords = ["동의해", "그렇게 하자", "좋은 의견", "결론", "정리하면", "알겠어"]
        return any(kw in recent for kw in end_keywords)

    async def _summarize_conclusion(
        self,
        log: list[dict],
        name_a: str,
        name_b: str,
        topic: str,
    ) -> str:
        """대화 결론 요약."""
        conv_text = "\n".join(f"{m['speaker']}: {m['content']}" for m in log)

        prompt = f"""{name_a}와 {name_b}의 대화 ({topic}):

{conv_text}

위 대화의 핵심 결론을 2-3문장으로 요약하세요.
투자 판단에 참고할 수 있는 구체적인 내용을 포함하세요."""

        return await self._gemini.generate(
            prompt,
            tier="medium",
            max_tokens=200,
        )

    async def _summarize_meeting(
        self,
        log: list[dict],
        topic: str,
        meeting_type: str,
    ) -> str:
        """미팅 결론 요약."""
        conv_text = "\n".join(f"{m['speaker']}: {m['content']}" for m in log)

        meeting_type_kr = {
            "morning": "장 시작 전 브리핑",
            "midday": "점심 중간 점검",
            "closing": "장 마감 리뷰",
            "emergency": "긴급 소집",
            "regular": "정기 미팅",
        }.get(meeting_type, meeting_type)

        prompt = f"""[{meeting_type_kr}] 주제: {topic}

{conv_text}

이 미팅의 핵심 내용을 3-4문장으로 요약하세요.
각 에이전트의 주요 의견과 최종 합의/결론을 포함하세요."""

        return await self._gemini.generate(
            prompt,
            tier="medium",
            max_tokens=300,
        )

    def get_recent_conversations(self, limit: int = 10) -> list[dict]:
        """최근 대화 목록."""
        return self._active_conversations[-limit:]
