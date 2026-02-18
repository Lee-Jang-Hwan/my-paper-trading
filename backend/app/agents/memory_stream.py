"""
메모리 스트림 (Memory Stream) 엔진

Stanford Generative Agents 아키텍처의 핵심 모듈.
에이전트가 경험한 모든 관찰, 대화, 성찰, 계획을 저장하고
최근성/중요도/관련성 3축 가중 검색으로 관련 기억을 추출합니다.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import get_supabase_client
from app.services.gemini_client import get_gemini_client

logger = logging.getLogger("memory_stream")

# 검색 가중치 기본값
ALPHA_RECENCY = 1.0
ALPHA_IMPORTANCE = 1.0
ALPHA_RELEVANCE = 1.0

# 최근성 지수 감쇠 상수 (시간 단위)
DECAY_FACTOR = 0.995


class MemoryStream:
    """에이전트 메모리 스트림 관리."""

    def __init__(self, agent_type: str):
        """
        Args:
            agent_type: 에이전트 유형 (trend, advisor, news, portfolio)
        """
        self.agent_type = agent_type
        self._sb = get_supabase_client()
        self._gemini = get_gemini_client()
        # 리플렉션 트리거용 중요도 누적
        self._importance_accumulator = 0.0
        self._reflection_threshold = 50.0  # 중요도 합이 이 값을 넘으면 리플렉션 트리거

    # ── 메모리 추가 ────────────────────────────────────────────

    async def add_memory(
        self,
        content: str,
        memory_type: str = "observation",
        importance: float | None = None,
        related_stocks: list[str] | None = None,
    ) -> dict | None:
        """
        새 메모리를 스트림에 추가.

        Args:
            content: 메모리 내용 (자연어)
            memory_type: observation, conversation, reflection, plan
            importance: 중요도 (None이면 LLM이 자동 채점)
            related_stocks: 관련 종목코드 리스트
        """
        # 중요도 자동 채점
        if importance is None:
            importance = await self._gemini.score_importance(content)

        # 임베딩 생성
        embedding = await self._gemini.embed_text(content)

        data: dict[str, Any] = {
            "agent_type": self.agent_type,
            "memory_type": memory_type,
            "content": content,
            "importance_score": round(importance, 1),
            "related_stock_codes": related_stocks or [],
        }

        if embedding:
            data["embedding"] = embedding

        try:
            result = self._sb.table("agent_memories").insert(data).execute()
            if result.data:
                # 중요도 누적 (리플렉션 트리거용)
                self._importance_accumulator += importance
                logger.debug(
                    f"[{self.agent_type}] 메모리 추가: {memory_type} "
                    f"(중요도: {importance:.1f}, 누적: {self._importance_accumulator:.1f})"
                )
                return result.data[0]
        except Exception as e:
            logger.error(f"메모리 저장 실패: {e}")
        return None

    async def add_observation(self, content: str, related_stocks: list[str] | None = None) -> dict | None:
        """관찰 메모리 추가."""
        return await self.add_memory(content, "observation", related_stocks=related_stocks)

    async def add_conversation(self, content: str, related_stocks: list[str] | None = None) -> dict | None:
        """대화 메모리 추가."""
        return await self.add_memory(content, "conversation", related_stocks=related_stocks)

    async def add_reflection(self, content: str, related_stocks: list[str] | None = None) -> dict | None:
        """성찰 메모리 추가 (높은 중요도)."""
        return await self.add_memory(content, "reflection", importance=8.0, related_stocks=related_stocks)

    async def add_plan(self, content: str) -> dict | None:
        """계획 메모리 추가."""
        return await self.add_memory(content, "plan", importance=3.0)

    # ── 메모리 검색 ────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        k: int = 10,
        *,
        alpha_recency: float = ALPHA_RECENCY,
        alpha_importance: float = ALPHA_IMPORTANCE,
        alpha_relevance: float = ALPHA_RELEVANCE,
        memory_types: list[str] | None = None,
    ) -> list[dict]:
        """
        3축 가중 검색으로 관련 메모리 검색.

        최종 점수 = alpha_recency * 최근성 + alpha_importance * 중요도 + alpha_relevance * 관련성
        각 축은 [0, 1]로 정규화됩니다.
        """
        # 후보 메모리 조회 (최근 200개)
        query_builder = (
            self._sb.table("agent_memories")
            .select("*")
            .eq("agent_type", self.agent_type)
            .is_("archived_at", "null")
            .order("created_at", desc=True)
            .limit(200)
        )

        if memory_types:
            query_builder = query_builder.in_("memory_type", memory_types)

        result = query_builder.execute()
        candidates = result.data or []

        if not candidates:
            return []

        # 쿼리 임베딩 생성 (관련성 계산용)
        query_embedding = await self._gemini.embed_query(query)

        now = datetime.now(timezone.utc)
        scored = []

        for mem in candidates:
            # 최근성 점수 (지수 감쇠)
            created = datetime.fromisoformat(mem["created_at"].replace("Z", "+00:00"))
            hours_ago = (now - created).total_seconds() / 3600
            recency_score = math.pow(DECAY_FACTOR, hours_ago)

            # 중요도 점수 (0-1 정규화)
            importance_score = mem.get("importance_score", 5.0) / 10.0

            # 관련성 점수 (코사인 유사도)
            relevance_score = 0.5  # 기본값
            if query_embedding and mem.get("embedding"):
                relevance_score = self._cosine_similarity(query_embedding, mem["embedding"])

            # 가중합
            final_score = (
                alpha_recency * recency_score
                + alpha_importance * importance_score
                + alpha_relevance * relevance_score
            )

            scored.append({
                **mem,
                "_recency": round(recency_score, 4),
                "_importance": round(importance_score, 4),
                "_relevance": round(relevance_score, 4),
                "_final_score": round(final_score, 4),
            })

        # 점수 순 정렬 후 상위 k개
        scored.sort(key=lambda x: x["_final_score"], reverse=True)

        # 접근 시간 업데이트 (최근성에 영향)
        top_ids = [m["id"] for m in scored[:k]]
        if top_ids:
            try:
                self._sb.table("agent_memories").update({
                    "last_accessed_at": now.isoformat(),
                }).in_("id", top_ids).execute()
            except Exception:
                pass

        return scored[:k]

    async def retrieve_recent(self, n: int = 100) -> list[dict]:
        """최근 n개 메모리 시간순 조회."""
        result = (
            self._sb.table("agent_memories")
            .select("*")
            .eq("agent_type", self.agent_type)
            .is_("archived_at", "null")
            .order("created_at", desc=True)
            .limit(n)
            .execute()
        )
        return result.data or []

    # ── 리플렉션 트리거 ────────────────────────────────────────

    def should_reflect(self) -> bool:
        """리플렉션이 필요한지 확인."""
        return self._importance_accumulator >= self._reflection_threshold

    def reset_reflection_accumulator(self) -> None:
        """리플렉션 후 누적기 초기화."""
        self._importance_accumulator = 0.0

    # ── 유틸리티 ───────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """코사인 유사도 계산."""
        if len(vec_a) != len(vec_b):
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_a * norm_b)))

    async def get_stats(self) -> dict:
        """메모리 통계."""
        result = (
            self._sb.table("agent_memories")
            .select("memory_type", count="exact")
            .eq("agent_type", self.agent_type)
            .is_("archived_at", "null")
            .execute()
        )
        return {
            "agent_type": self.agent_type,
            "total_memories": result.count or 0,
            "importance_accumulator": round(self._importance_accumulator, 1),
            "reflection_threshold": self._reflection_threshold,
        }
