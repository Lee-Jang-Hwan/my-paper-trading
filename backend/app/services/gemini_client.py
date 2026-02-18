"""
Gemini API 클라이언트

Google Gemini API를 래핑하여 에이전트 시스템에서 사용합니다.
- 텍스트 생성 (대화, 분석, 리플렉션)
- 텍스트 임베딩 (메모리 검색용 768차원 벡터)
- 중요도 점수 채점
- 일일 토큰 사용량 관리
"""

import asyncio
import json
import logging
from datetime import date
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings

logger = logging.getLogger("gemini_client")

# 모델 티어 (비용 최적화)
MODEL_TIER = {
    "high": "gemini-2.0-flash",       # 복잡한 분석, 리플렉션, 대화
    "medium": "gemini-2.0-flash",     # 계획 수립, 중요도 채점
    "low": "gemini-2.0-flash-lite",   # 단순 분류, 임베딩 판단
}

EMBEDDING_MODEL = "gemini-embedding-001"


class GeminiClient:
    """Gemini API 래퍼."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.GEMINI_API_KEY
        self._daily_limit = settings.AGENT_DAILY_TOKEN_LIMIT
        self._today: date | None = None
        self._tokens_used = 0
        self._lock = asyncio.Semaphore(3)  # 최대 3개 동시 요청 허용
        self._token_lock = asyncio.Lock()  # 토큰 카운터 보호용
        self._client = None

        if self._api_key:
            self._client = genai.Client(api_key=self._api_key)
            logger.info("Gemini API 초기화 완료")
        else:
            logger.warning("GEMINI_API_KEY가 설정되지 않았습니다. 에이전트 LLM 기능 비활성화.")

    def _reset_daily_counter(self) -> None:
        """일일 토큰 카운터 리셋."""
        today = date.today()
        if self._today != today:
            self._today = today
            self._tokens_used = 0

    async def _check_budget(self, estimated_tokens: int = 1000) -> bool:
        """토큰 예산 확인 (락으로 보호)."""
        async with self._token_lock:
            self._reset_daily_counter()
            return (self._tokens_used + estimated_tokens) <= self._daily_limit

    async def _track_usage(self, response) -> None:
        """응답에서 토큰 사용량 추적 (락으로 보호)."""
        async with self._token_lock:
            try:
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    total = getattr(response.usage_metadata, "total_token_count", 0)
                    self._tokens_used += total
            except Exception:
                self._tokens_used += 500  # 추적 실패 시 보수적 추정

    # ── 텍스트 생성 ────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        tier: str = "high",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """텍스트 생성."""
        if not self._client:
            return "[LLM 비활성화] API 키가 설정되지 않았습니다."

        if not await self._check_budget(max_tokens):
            logger.warning(f"일일 토큰 한도 초과 ({self._tokens_used}/{self._daily_limit})")
            return "[토큰 한도 초과] 오늘의 AI 분석 예산을 모두 사용했습니다."

        model_name = MODEL_TIER.get(tier, MODEL_TIER["high"])

        async with self._lock:
            try:
                config = types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    system_instruction=system_instruction,
                )
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                await self._track_usage(response)
                return response.text or ""
            except Exception as e:
                logger.error(f"Gemini 생성 오류: {e}")
                return f"[LLM 오류] {str(e)[:100]}"

    async def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        tier: str = "medium",
    ) -> dict | list | None:
        """JSON 형식으로 텍스트 생성 후 파싱."""
        full_prompt = prompt + "\n\n반드시 유효한 JSON만 출력하세요. 다른 텍스트는 포함하지 마세요."
        text = await self.generate(
            full_prompt,
            system_instruction=system_instruction,
            tier=tier,
            temperature=0.3,
        )
        # JSON 추출
        text = text.strip()
        if text.startswith("```"):
            # 코드 블록 제거
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"JSON 파싱 실패: {text[:200]}")
            return None

    # ── 중요도 점수 채점 ───────────────────────────────────────

    async def score_importance(self, memory_content: str) -> float:
        """
        메모리 내용의 중요도를 1~10점으로 채점.
        1: 일상적/반복적 관찰 (KOSPI +0.1%)
        10: 극히 중요한 이벤트 (실적 서프라이즈, 급등락, 긴급 속보)
        """
        prompt = f"""다음 주식시장 관련 정보의 중요도를 1~10 사이의 숫자 하나로만 답하세요.

1점: 일상적, 반복적 관찰 (예: "KOSPI 소폭 상승 +0.1%")
3점: 일반적 변동 (예: "외국인 소폭 순매수")
5점: 주목할 만한 변화 (예: "삼성전자 거래량 급증")
7점: 중요한 이벤트 (예: "한국은행 기준금리 동결 결정")
9점: 매우 중요 (예: "삼성전자 실적 서프라이즈, 컨센서스 +15%")
10점: 극도로 중요 (예: "서킷브레이커 발동", "대규모 경제위기 신호")

정보: {memory_content}

숫자만 답하세요:"""

        result = await self.generate(prompt, tier="low", temperature=0.1, max_tokens=10)
        try:
            score = float(result.strip().split()[0])
            return max(1.0, min(10.0, score))
        except (ValueError, IndexError):
            return 5.0  # 기본값

    # ── 임베딩 생성 ────────────────────────────────────────────

    async def embed_text(self, text: str) -> list[float] | None:
        """텍스트를 768차원 벡터로 임베딩."""
        if not self._client:
            return None

        try:
            result = await asyncio.to_thread(
                self._client.models.embed_content,
                model=EMBEDDING_MODEL,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=768,
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"임베딩 생성 오류: {e}")
            return None

    async def embed_query(self, query: str) -> list[float] | None:
        """검색 쿼리를 벡터로 임베딩 (retrieval_query 타입)."""
        if not self._client:
            return None

        try:
            result = await asyncio.to_thread(
                self._client.models.embed_content,
                model=EMBEDDING_MODEL,
                contents=query,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=768,
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"쿼리 임베딩 오류: {e}")
            return None

    # ── 상태 조회 ──────────────────────────────────────────────

    @property
    def tokens_used_today(self) -> int:
        self._reset_daily_counter()
        return self._tokens_used

    @property
    def tokens_remaining(self) -> int:
        self._reset_daily_counter()
        return max(0, self._daily_limit - self._tokens_used)

    @property
    def is_available(self) -> bool:
        return self._client is not None


# ── 싱글턴 ────────────────────────────────────────────────────

_client: GeminiClient | None = None


def get_gemini_client() -> GeminiClient:
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
