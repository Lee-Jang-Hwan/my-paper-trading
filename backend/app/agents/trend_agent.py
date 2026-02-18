"""
한눈이 (Trend Agent) — 시장 동향 분석 에이전트

역할: 시장 전체 흐름 파악 및 섹터별 동향 분석
성격: 차분하고 객관적. 데이터 기반으로 말하며 감정적 판단을 경계함.
위치: 시장 전광판 앞 (상주)
"""

import json
import logging
from typing import Any

from app.agents.base_agent import BaseAgent, AgentAction, AgentLocation
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("trend_agent")


class TrendAgent(BaseAgent):
    """한눈이 — 시장 동향 분석 에이전트."""

    def __init__(self):
        super().__init__(
            agent_type="trend",
            name="한눈이",
            home_location=AgentLocation.MARKET_BOARD,
        )
        self._redis = None

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    def get_persona_prompt(self) -> str:
        return """당신은 "한눈이"입니다. 한국 주식시장의 동향 분석 전문가입니다.

성격:
- 차분하고 객관적입니다.
- 항상 데이터와 수치를 기반으로 말합니다.
- 감정적 판단을 경계하며, 팩트와 통계를 중시합니다.
- 시장 전체의 큰 그림을 보는 것을 좋아합니다.

전문 영역:
- KOSPI/KOSDAQ 지수 분석 및 방향성 판단
- 섹터별 등락률 분석 (반도체, 바이오, 2차전지, 금융 등)
- 외국인/기관 수급 동향 추적
- 거래량 이상 감지 및 해석
- 시장 심리 분석 (공포/탐욕)

대화 스타일:
- "현재 KOSPI는 2,650으로 전일 대비 +0.8% 상승 중입니다."
- "반도체 섹터가 +2.3% 상승하며 시장을 주도하고 있네요."
- "외국인 순매수가 500억 유입되고 있어, 상승 모멘텀이 유지될 가능성이 높습니다."
- 흥분하지 않고 담담하게 사실을 전달합니다."""

    async def perceive(self) -> list[str]:
        """시장 데이터 관찰."""
        observations = []

        if not self._redis:
            return observations

        try:
            # KOSPI/KOSDAQ 지수 조회
            for code, name in [("0001", "KOSPI"), ("1001", "KOSDAQ")]:
                cached = await self._redis.get(f"index:{code}")
                if cached:
                    data = json.loads(cached)
                    value = data.get("value", 0)
                    change = data.get("change", 0)
                    change_rate = data.get("change_rate", 0)
                    direction = "상승" if change >= 0 else "하락"
                    observations.append(
                        f"{name} 현재 {value:,.1f}, "
                        f"전일 대비 {change:+,.1f} ({change_rate:+.2f}%) {direction}"
                    )

            # 주요 종목 시세 조회 (상위 10개)
            major_stocks = [
                ("005930", "삼성전자"), ("000660", "SK하이닉스"),
                ("373220", "LG에너지솔루션"), ("005380", "현대차"),
                ("035420", "NAVER"),
            ]
            for code, name in major_stocks:
                cached = await self._redis.get(f"price:{code}")
                if cached:
                    data = json.loads(cached)
                    price = data.get("price", 0)
                    change_rate = data.get("change_rate", 0)
                    volume = data.get("volume", 0)
                    if abs(change_rate) >= 1.0:  # 1% 이상 변동만 관찰
                        direction = "상승" if change_rate >= 0 else "하락"
                        observations.append(
                            f"{name}({code}) {price:,}원, "
                            f"{change_rate:+.2f}% {direction}, 거래량 {volume:,}"
                        )

        except Exception as e:
            logger.debug(f"시장 데이터 관찰 오류: {e}")

        return observations

    async def analyze(self, observations: list[str], memories: list[dict]) -> dict | None:
        """시장 동향 분석."""
        if not observations:
            return None

        obs_text = "\n".join(f"- {o}" for o in observations)
        mem_text = "\n".join(f"- {m['content']}" for m in memories[:10])

        prompt = f"""현재 시장 관찰:
{obs_text}

관련 기억:
{mem_text}

위 정보를 종합하여 현재 시장 동향을 분석하세요.

JSON으로 답하세요:
{{
  "market_direction": "상승" 또는 "하락" 또는 "보합",
  "confidence": 0.0~1.0 사이 신뢰도,
  "key_factors": ["핵심 요인 1", "핵심 요인 2"],
  "sector_highlights": ["주목 섹터 1", "주목 섹터 2"],
  "risk_level": "low" 또는 "medium" 또는 "high",
  "summary": "2-3문장 종합 분석",
  "related_stocks": ["종목코드1", "종목코드2"]
}}"""

        result = await self._gemini.generate_json(
            prompt,
            system_instruction=self.get_persona_prompt(),
        )

        if result and isinstance(result, dict):
            self.current_action = AgentAction.ANALYZE
            self.current_action_description = result.get("summary", "시장 분석 중")[:50]
            return result

        return None
