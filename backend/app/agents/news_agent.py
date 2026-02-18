"""
번개 (News Agent) — 뉴스 캐치 에이전트

역할: 실시간 뉴스/공시/속보 모니터링 및 영향 분석
성격: 빠르고 간결함. 속보에 민감하며 항상 바삐 움직임.
위치: 뉴스 터미널 (상주)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.base_agent import BaseAgent, AgentAction, AgentLocation
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("news_agent")


class NewsAgent(BaseAgent):
    """번개 — 뉴스 캐치 에이전트."""

    def __init__(self):
        super().__init__(
            agent_type="news",
            name="번개",
            home_location=AgentLocation.NEWS_TERMINAL,
        )
        self._redis = None
        self._seen_news_ids: set[str] = set()  # 이미 처리한 뉴스 ID

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    def get_persona_prompt(self) -> str:
        return """당신은 "번개"입니다. 실시간 증권 뉴스 전문 에이전트입니다.

성격:
- 빠르고 간결합니다. 핵심만 전달합니다.
- 속보에 매우 민감하며, 중요한 뉴스를 놓치지 않습니다.
- 가끔 흥분하기도 하지만, 분석은 객관적입니다.
- 항상 바삐 움직이며 정보를 수집합니다.

전문 영역:
- 실시간 증권 뉴스 모니터링
- 속보 감지 및 즉시 알림
- 뉴스 영향도 분석 (호재/악재/중립)
- 관련 종목 자동 매핑
- 공시 정보 해석 (유상증자, 실적발표, M&A 등)

대화 스타일:
- "속보! 삼성전자 4분기 영업이익 12조, 컨센서스 +15% 서프라이즈!"
- "이 뉴스는 반도체 섹터 전체에 호재로 작용할 수 있어!"
- "한국은행 기준금리 동결, 시장 예상대로야. 영향은 제한적일 듯."
- 긴급한 뉴스일수록 더 흥분된 어조를 사용합니다."""

    async def perceive(self) -> list[str]:
        """뉴스 피드 관찰."""
        observations = []
        sb = get_supabase_client()

        try:
            # DB에서 최근 뉴스 조회
            result = (
                sb.table("news")
                .select("id, title, source, sentiment_score, related_stocks, published_at")
                .order("published_at", desc=True)
                .limit(10)
                .execute()
            )

            for news in (result.data or []):
                news_id = news["id"]
                if news_id in self._seen_news_ids:
                    continue

                self._seen_news_ids.add(news_id)
                title = news.get("title", "")
                source = news.get("source", "")
                score = news.get("sentiment_score")  # -1.0 ~ 1.0
                stocks = news.get("related_stocks", [])

                # 감성 점수를 한글 라벨로 변환
                if score is not None and score > 0.2:
                    sentiment_kr = "호재"
                elif score is not None and score < -0.2:
                    sentiment_kr = "악재"
                else:
                    sentiment_kr = "중립"
                stocks_str = ", ".join(stocks[:3]) if stocks else "미특정"

                observations.append(
                    f"[{source}] {title} (감성: {sentiment_kr}, 관련종목: {stocks_str})"
                )

            # seen 목록 크기 제한
            if len(self._seen_news_ids) > 500:
                self._seen_news_ids = set(list(self._seen_news_ids)[-200:])

        except Exception as e:
            logger.debug(f"뉴스 관찰 오류: {e}")

        # Redis에서 시장 급변 감지
        if self._redis:
            try:
                for code, name in [("005930", "삼성전자"), ("000660", "SK하이닉스")]:
                    cached = await self._redis.get(f"price:{code}")
                    if cached:
                        data = json.loads(cached)
                        change_rate = data.get("change_rate", 0)
                        if abs(change_rate) >= 3.0:  # 3% 이상 급변
                            direction = "급등" if change_rate > 0 else "급락"
                            observations.append(
                                f"[시장속보] {name}({code}) {change_rate:+.2f}% {direction}! "
                                f"현재가 {data.get('price', 0):,}원"
                            )
            except Exception:
                pass

        return observations

    async def analyze(self, observations: list[str], memories: list[dict]) -> dict | None:
        """뉴스 영향 분석."""
        if not observations:
            return None

        obs_text = "\n".join(f"- {o}" for o in observations)
        mem_text = "\n".join(f"- {m['content']}" for m in memories[:10])

        prompt = f"""새로 감지된 뉴스/정보:
{obs_text}

관련 기억:
{mem_text}

위 뉴스들을 분석하여 시장 영향을 평가하세요.

JSON으로 답하세요:
{{
  "news_items": [
    {{
      "title": "뉴스 제목/요약",
      "sentiment": "positive" 또는 "negative" 또는 "neutral",
      "impact_level": "high" 또는 "medium" 또는 "low",
      "affected_sectors": ["영향받는 섹터"],
      "affected_stocks": ["종목코드"],
      "analysis": "1-2문장 영향 분석"
    }}
  ],
  "urgent": true 또는 false,
  "notify_agents": ["대화 필요한 에이전트 agent_type"],
  "summary": "2-3문장 종합 뉴스 브리핑",
  "related_stocks": ["종목코드"]
}}"""

        result = await self._gemini.generate_json(
            prompt,
            system_instruction=self.get_persona_prompt(),
        )

        if result and isinstance(result, dict):
            is_urgent = result.get("urgent", False)
            self.current_action = AgentAction.EXCITED if is_urgent else AgentAction.ANALYZE
            self.current_action_description = result.get("summary", "뉴스 분석 중")[:50]
            return result

        return None

    async def get_daily_briefing(self) -> str:
        """일일 뉴스 브리핑 생성."""
        memories = await self.memory.retrieve_recent(50)
        news_memories = [m for m in memories if "뉴스" in m.get("content", "") or "[" in m.get("content", "")]

        if not news_memories:
            return "오늘은 아직 주목할 만한 뉴스가 없습니다."

        news_text = "\n".join(f"- {m['content']}" for m in news_memories[:20])

        prompt = f"""오늘의 주요 뉴스들:
{news_text}

위 뉴스들을 종합하여 오늘의 뉴스 브리핑을 작성하세요.
- 가장 중요한 뉴스 3개를 선정
- 각 뉴스의 시장 영향 분석
- 전체적인 뉴스 톤(호재 우세/악재 우세/중립)

번개의 말투로 간결하고 핵심적으로 작성하세요."""

        return await self._gemini.generate(
            prompt,
            system_instruction=self.get_persona_prompt(),
            max_tokens=500,
        )
