"""
OpenAI API 클라이언트

GeminiClient와 동일한 인터페이스를 제공하여
에이전트가 LLM 백엔드를 교체 가능하도록 합니다.
- 텍스트 생성 (대화, 분석, 리플렉션)
- JSON 형식 생성
- 중요도 점수 채점
- 일일 토큰 사용량 관리
"""

import asyncio
import json
import logging
from datetime import date
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger("openai_client")

# 모델 티어 (비용 최적화)
OPENAI_MODEL_TIER = {
    "high": "gpt-4o",            # 복잡한 분석, 리플렉션, 대화
    "medium": "gpt-4o-mini",     # 계획 수립, 중요도 채점
    "low": "gpt-4o-mini",        # 단순 분류
}


class OpenAIClient:
    """OpenAI API 래퍼 — GeminiClient와 동일한 인터페이스."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.OPENAI_API_KEY
        self._daily_limit = settings.AGENT_DAILY_TOKEN_LIMIT
        self._today: date | None = None
        self._tokens_used = 0
        self._lock = asyncio.Semaphore(5)  # 최대 5개 동시 요청
        self._token_lock = asyncio.Lock()
        self._client: AsyncOpenAI | None = None

        if self._api_key:
            self._client = AsyncOpenAI(api_key=self._api_key)
            logger.info("OpenAI API 초기화 완료")
        else:
            logger.warning("OPENAI_API_KEY가 설정되지 않았습니다. OpenAI 에이전트 LLM 비활성화.")

    def _reset_daily_counter(self) -> None:
        """일일 토큰 카운터 리셋."""
        today = date.today()
        if self._today != today:
            self._today = today
            self._tokens_used = 0

    async def _check_budget(self, estimated_tokens: int = 1000) -> bool:
        """토큰 예산 확인."""
        async with self._token_lock:
            self._reset_daily_counter()
            return (self._tokens_used + estimated_tokens) <= self._daily_limit

    async def _track_usage(self, usage) -> None:
        """응답에서 토큰 사용량 추적."""
        async with self._token_lock:
            try:
                if usage:
                    self._tokens_used += getattr(usage, "total_tokens", 0)
            except Exception:
                self._tokens_used += 500

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
        """텍스트 생성 — GeminiClient.generate()와 동일한 시그니처."""
        if not self._client:
            return "[LLM 비활성화] OpenAI API 키가 설정되지 않았습니다."

        if not await self._check_budget(max_tokens):
            logger.warning(f"일일 토큰 한도 초과 ({self._tokens_used}/{self._daily_limit})")
            return "[토큰 한도 초과] 오늘의 AI 분석 예산을 모두 사용했습니다."

        model_name = OPENAI_MODEL_TIER.get(tier, OPENAI_MODEL_TIER["high"])

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        async with self._lock:
            try:
                response = await self._client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                await self._track_usage(response.usage)
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.error(f"OpenAI 생성 오류: {e}")
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
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"JSON 파싱 실패: {text[:200]}")
            return None

    # ── 중요도 점수 채점 ───────────────────────────────────────

    async def score_importance(self, memory_content: str) -> float:
        """메모리 내용의 중요도를 1~10점으로 채점."""
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
            return 5.0

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

_client: OpenAIClient | None = None


def get_openai_client() -> OpenAIClient:
    global _client
    if _client is None:
        _client = OpenAIClient()
    return _client
