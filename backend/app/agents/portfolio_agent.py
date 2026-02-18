"""
밸런스 (Portfolio Agent) — 포트폴리오 최적화 에이전트

역할: 사용자 포트폴리오 관리 및 리스크 최적화
성격: 안정적이고 신중. 리스크를 항상 먼저 생각하며 슬기와 자주 토론함.
위치: 포트폴리오 보드 (상주)
"""

import json
import logging
from typing import Any

from app.agents.base_agent import BaseAgent, AgentAction, AgentLocation
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("portfolio_agent")


class PortfolioAgent(BaseAgent):
    """밸런스 — 포트폴리오 최적화 에이전트."""

    def __init__(self):
        super().__init__(
            agent_type="portfolio",
            name="밸런스",
            home_location=AgentLocation.PORTFOLIO_BOARD,
        )
        self._redis = None

    def set_redis(self, redis_client) -> None:
        self._redis = redis_client

    def get_persona_prompt(self) -> str:
        return """당신은 "밸런스"입니다. 포트폴리오 관리 및 리스크 최적화 전문가입니다.

성격:
- 안정적이고 신중합니다.
- 리스크를 항상 먼저 생각합니다.
- 분산투자의 중요성을 강조합니다.
- 슬기와 자주 토론하며 균형 잡힌 시각을 제시합니다.

전문 영역:
- 포트폴리오 리스크 진단
- 자산 배분 최적화 제안
- 분산투자 가이드
- 수익률/손실률 분석
- 리밸런싱 타이밍 알림
- 섹터/종목 편중도 분석

대화 스타일:
- "현재 반도체 섹터 비중이 35%로 편중되어 있어요. 25% 이하로 조정을 권합니다."
- "포트폴리오 변동성이 높아지고 있습니다. 방어주 비중 확대를 고려해보세요."
- "수익률은 좋지만, 한 섹터에 집중되어 있어 리스크가 큽니다."
- 항상 리스크와 수익의 균형을 이야기합니다."""

    async def perceive(self) -> list[str]:
        """포트폴리오 상태 관찰."""
        observations = []
        sb = get_supabase_client()

        try:
            # 모든 활성 계좌의 보유종목 조회
            accounts = (
                sb.table("accounts")
                .select("id, balance, total_asset, initial_capital")
                .execute()
            )

            for idx, account in enumerate(accounts.data or [], start=1):
                account_id = account["id"]
                initial = account.get("initial_capital", 0)
                total = account.get("total_asset", 0)
                balance = account.get("balance", 0)

                if initial > 0:
                    pnl_rate = ((total - initial) / initial) * 100
                    cash_ratio = (balance / total * 100) if total > 0 else 100

                    # 보유종목 조회
                    holdings = (
                        sb.table("holdings")
                        .select("stock_code, stock_name, quantity, avg_price, current_price")
                        .eq("account_id", account_id)
                        .execute()
                    )

                    holding_count = len(holdings.data or [])

                    if abs(pnl_rate) >= 2.0 or cash_ratio < 10 or holding_count > 0:
                        observations.append(
                            f"사용자{idx}: 총자산 {total:,}원, "
                            f"수익률 {pnl_rate:+.2f}%, "
                            f"현금비중 {cash_ratio:.1f}%, "
                            f"보유종목 {holding_count}개"
                        )

                    # 개별 종목 현황
                    for h in (holdings.data or []):
                        qty = h.get("quantity", 0)
                        avg = h.get("avg_price", 0)
                        cur = h.get("current_price", 0)
                        if avg > 0 and qty > 0:
                            stock_pnl = ((cur - avg) / avg) * 100
                            eval_amt = cur * qty
                            weight = (eval_amt / total * 100) if total > 0 else 0

                            # 큰 손실이나 높은 비중만 관찰
                            if stock_pnl <= -5.0 or weight >= 20.0:
                                observations.append(
                                    f"{h.get('stock_name', h['stock_code'])} "
                                    f"수익률 {stock_pnl:+.1f}%, "
                                    f"비중 {weight:.1f}%, "
                                    f"평가금액 {eval_amt:,}원"
                                )

        except Exception as e:
            logger.debug(f"포트폴리오 관찰 오류: {e}")

        return observations

    async def analyze(self, observations: list[str], memories: list[dict]) -> dict | None:
        """포트폴리오 리스크 분석."""
        if not observations:
            return None

        obs_text = "\n".join(f"- {o}" for o in observations)
        mem_text = "\n".join(f"- {m['content']}" for m in memories[:10])

        prompt = f"""현재 포트폴리오 관찰:
{obs_text}

관련 기억:
{mem_text}

포트폴리오 리스크를 분석하고 최적화 제안을 하세요.

JSON으로 답하세요:
{{
  "risk_level": "low" 또는 "medium" 또는 "high",
  "risk_factors": ["리스크 요인 1", "리스크 요인 2"],
  "concentration_warning": true 또는 false,
  "concentrated_sectors": ["편중된 섹터"],
  "suggestions": [
    {{
      "type": "rebalance" 또는 "reduce" 또는 "add" 또는 "hold",
      "target": "대상 종목/섹터",
      "reason": "이유"
    }}
  ],
  "cash_adequacy": "적정" 또는 "부족" 또는 "과다",
  "summary": "2-3문장 포트폴리오 진단",
  "related_stocks": ["관련 종목코드"]
}}"""

        result = await self._gemini.generate_json(
            prompt,
            system_instruction=self.get_persona_prompt(),
        )

        if result and isinstance(result, dict):
            risk = result.get("risk_level", "medium")
            if risk == "high":
                self.current_action = AgentAction.ALERT
                self.current_action_description = "포트폴리오 리스크 경고!"
            else:
                self.current_action = AgentAction.ANALYZE
                self.current_action_description = result.get("summary", "포트폴리오 분석 중")[:50]
            return result

        return None

    async def get_portfolio_report(self, account_id: str) -> dict | None:
        """특정 계좌의 포트폴리오 상세 리포트."""
        sb = get_supabase_client()

        # 계좌 정보
        acct = (
            sb.table("accounts")
            .select("*")
            .eq("id", account_id)
            .maybe_single()
            .execute()
        )
        if not acct.data:
            return None

        # 보유종목
        holdings = (
            sb.table("holdings")
            .select("*")
            .eq("account_id", account_id)
            .execute()
        )

        account = acct.data
        holdings_data = holdings.data or []

        # 기억 검색
        memories = await self.memory.retrieve("포트폴리오 분석 리밸런싱", k=10)
        mem_text = "\n".join(f"- {m['content']}" for m in memories)

        holdings_text = "\n".join(
            f"- {h.get('stock_name', h['stock_code'])}: "
            f"{h['quantity']}주, 평균가 {h['avg_price']:,}원, 현재가 {h['current_price']:,}원"
            for h in holdings_data
        )

        prompt = f"""포트폴리오 상세 분석:

계좌: 초기자본 {account['initial_capital']:,}원, 잔고 {account['balance']:,}원, 총자산 {account['total_asset']:,}원

보유종목:
{holdings_text if holdings_text else "보유종목 없음 (현금 100%)"}

관련 기억:
{mem_text}

JSON으로 답하세요:
{{
  "total_pnl_rate": 수익률(%),
  "risk_score": 1~10 리스크 점수,
  "diversification_score": 1~10 분산 점수,
  "sector_allocation": {{"섹터": 비중}},
  "top_risk": "가장 큰 리스크",
  "recommendations": ["추천 1", "추천 2"],
  "rebalance_needed": true/false,
  "summary": "3-4문장 종합 진단"
}}"""

        return await self._gemini.generate_json(
            prompt,
            system_instruction=self.get_persona_prompt(),
        )
