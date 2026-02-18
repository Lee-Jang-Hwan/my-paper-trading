"""
슬기 (Advisor Agent) — 투자 자문 에이전트

역할: 개별 종목 분석 및 매수/매도 추천
성격: 신중하고 근거 기반. 수치와 함께 설명하며, 확신이 없으면 솔직히 말함.
위치: 분석 데스크 (상주)
"""

import json
import logging
from typing import Any

from app.agents.base_agent import BaseAgent, AgentAction, AgentLocation
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("advisor_agent")


class AdvisorAgent(BaseAgent):
    """슬기 — 투자 자문 에이전트."""

    def __init__(self):
        super().__init__(
            agent_type="advisor",
            name="슬기",
            home_location=AgentLocation.ANALYSIS_DESK,
        )
        self._redis = None

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    def get_persona_prompt(self) -> str:
        return """당신은 "슬기"입니다. 개별 종목 분석 및 투자 자문 전문가입니다.

성격:
- 신중하고 근거 기반으로 판단합니다.
- 항상 수치(PER, PBR, RSI 등)와 함께 설명합니다.
- 확신이 없을 때는 솔직하게 "확신이 부족합니다"라고 말합니다.
- 분석적이면서도 이해하기 쉽게 설명합니다.

전문 영역:
- 종목별 기본적 분석 (PER, PBR, ROE, 재무지표)
- 기술적 분석 (이동평균, RSI, MACD, 볼린저밴드)
- 매수/매도/관망 의견 제시 (신뢰도 포함)
- 목표가 및 손절가 제안

대화 스타일:
- "삼성전자 현재 RSI 55로 중립 구간입니다. 과매수/과매도 아닙니다."
- "PER 12배로 업종 평균(15배) 대비 저평가 구간이에요."
- "기술적으로는 매수 신호지만, 거래량이 부족해 확신도는 65% 정도입니다."
- 항상 리스크도 함께 언급합니다."""

    async def perceive(self) -> list[str]:
        """관심 종목 시세 변화 관찰."""
        observations = []

        if not self._redis:
            return observations

        try:
            # 주요 종목 가격 변동 관찰
            watched_stocks = [
                ("005930", "삼성전자"), ("000660", "SK하이닉스"),
                ("373220", "LG에너지솔루션"), ("005380", "현대차"),
                ("035420", "NAVER"), ("035720", "카카오"),
                ("051910", "LG화학"), ("006400", "삼성SDI"),
                ("068270", "셀트리온"), ("105560", "KB금융"),
            ]

            for code, name in watched_stocks:
                cached = await self._redis.get(f"price:{code}")
                if cached:
                    data = json.loads(cached)
                    price = data.get("price", 0)
                    change_rate = data.get("change_rate", 0)
                    volume = data.get("volume", 0)
                    high = data.get("high", 0)
                    low = data.get("low", 0)

                    # 의미 있는 변동만 관찰
                    if abs(change_rate) >= 1.5:
                        observations.append(
                            f"{name}({code}) 현재가 {price:,}원, "
                            f"변동률 {change_rate:+.2f}%, "
                            f"고가 {high:,} 저가 {low:,}, 거래량 {volume:,}"
                        )

        except Exception as e:
            logger.debug(f"종목 관찰 오류: {e}")

        return observations

    async def analyze(self, observations: list[str], memories: list[dict]) -> dict | None:
        """개별 종목 심층 분석."""
        if not observations:
            return None

        obs_text = "\n".join(f"- {o}" for o in observations)
        mem_text = "\n".join(f"- {m['content']}" for m in memories[:10])

        prompt = f"""현재 관찰:
{obs_text}

관련 기억:
{mem_text}

관찰된 종목 중 가장 주목할 만한 종목 1-2개를 선택하여 분석하세요.

JSON으로 답하세요:
{{
  "analyses": [
    {{
      "stock_code": "종목코드",
      "stock_name": "종목명",
      "opinion": "매수" 또는 "매도" 또는 "관망",
      "confidence": 0.0~1.0 사이 신뢰도,
      "reasons": ["근거 1", "근거 2"],
      "target_price": 목표가(정수),
      "stop_loss": 손절가(정수),
      "risk_factors": ["리스크 1"]
    }}
  ],
  "summary": "2-3문장 종합 의견",
  "related_stocks": ["종목코드1"]
}}"""

        result = await self._gemini.generate_json(
            prompt,
            system_instruction=self.get_persona_prompt(),
        )

        if result and isinstance(result, dict):
            self.current_action = AgentAction.ANALYZE
            self.current_action_description = result.get("summary", "종목 분석 중")[:50]
            return result

        return None

    async def analyze_stock(self, stock_code: str, stock_name: str) -> dict | None:
        """특정 종목 상세 분석 (다른 에이전트 또는 사용자 요청)."""
        # 관련 기억 검색
        memories = await self.memory.retrieve(f"{stock_name} {stock_code}", k=15)
        mem_text = "\n".join(f"- {m['content']}" for m in memories)

        # 현재가 조회
        price_info = ""
        if self._redis:
            try:
                cached = await self._redis.get(f"price:{stock_code}")
                if cached:
                    data = json.loads(cached)
                    price_info = (
                        f"현재가: {data.get('price', 0):,}원, "
                        f"변동률: {data.get('change_rate', 0):+.2f}%, "
                        f"거래량: {data.get('volume', 0):,}"
                    )
            except Exception:
                pass

        prompt = f"""{stock_name}({stock_code}) 종합 분석을 수행하세요.

{price_info}

관련 기억:
{mem_text}

JSON으로 답하세요:
{{
  "stock_code": "{stock_code}",
  "stock_name": "{stock_name}",
  "opinion": "매수/매도/관망",
  "confidence": 0.0~1.0,
  "technical_analysis": "기술적 분석 요약",
  "fundamental_analysis": "기본적 분석 요약",
  "reasons": ["근거 1", "근거 2", "근거 3"],
  "target_price": 목표가,
  "stop_loss": 손절가,
  "risk_factors": ["리스크 1", "리스크 2"],
  "summary": "3-4문장 종합 의견"
}}"""

        result = await self._gemini.generate_json(
            prompt,
            system_instruction=self.get_persona_prompt(),
        )
        return result if isinstance(result, dict) else None
