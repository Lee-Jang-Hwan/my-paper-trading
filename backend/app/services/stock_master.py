"""
종목 마스터 데이터 관리

KOSPI/KOSDAQ 전체 종목 목록을 1일 1회 수집하여 Supabase에 저장합니다.
"""

import logging
from datetime import datetime

from app.db.supabase_client import get_supabase_client
from app.services.kis_api import get_kis_client

logger = logging.getLogger("stock_master")

# 주요 종목 리스트 (초기 시드 데이터)
MAJOR_STOCKS = [
    ("005930", "삼성전자", "KOSPI", "반도체"),
    ("000660", "SK하이닉스", "KOSPI", "반도체"),
    ("373220", "LG에너지솔루션", "KOSPI", "2차전지"),
    ("005380", "현대차", "KOSPI", "자동차"),
    ("000270", "기아", "KOSPI", "자동차"),
    ("068270", "셀트리온", "KOSPI", "바이오"),
    ("035420", "NAVER", "KOSPI", "인터넷"),
    ("035720", "카카오", "KOSPI", "인터넷"),
    ("051910", "LG화학", "KOSPI", "화학"),
    ("006400", "삼성SDI", "KOSPI", "2차전지"),
    ("003670", "포스코퓨처엠", "KOSPI", "소재"),
    ("055550", "신한지주", "KOSPI", "금융"),
    ("105560", "KB금융", "KOSPI", "금융"),
    ("096770", "SK이노베이션", "KOSPI", "에너지"),
    ("003550", "LG", "KOSPI", "지주"),
    ("247540", "에코프로비엠", "KOSDAQ", "2차전지"),
    ("086520", "에코프로", "KOSDAQ", "2차전지"),
    ("403870", "HPSP", "KOSDAQ", "반도체장비"),
    ("293490", "카카오게임즈", "KOSDAQ", "게임"),
    ("328130", "루닛", "KOSDAQ", "AI/의료"),
]


async def seed_major_stocks() -> int:
    """주요 종목 시드 데이터 삽입 (최초 1회)."""
    sb = get_supabase_client()
    inserted = 0

    for code, name, market, sector in MAJOR_STOCKS:
        try:
            sb.table("stock_master").upsert(
                {
                    "stock_code": code,
                    "stock_name": name,
                    "market": market,
                    "sector": sector,
                    "is_active": True,
                    "updated_at": datetime.now().isoformat(),
                },
                on_conflict="stock_code",
            ).execute()
            inserted += 1
        except Exception as e:
            logger.warning(f"종목 시드 삽입 실패 ({code}): {e}")

    logger.info(f"주요 종목 시드 데이터: {inserted}건 삽입/갱신")
    return inserted


async def update_stock_prices_cache() -> int:
    """
    주요 종목 현재가를 일괄 조회하여 Supabase에 저장.
    1일 1회 장 마감 후 실행 권장.
    """
    kis = get_kis_client()
    sb = get_supabase_client()
    updated = 0

    for code, name, _, _ in MAJOR_STOCKS:
        try:
            price = await kis.get_current_price(code)
            if price["price"] > 0:
                sb.table("stock_master").update(
                    {
                        "market_cap": price.get("market_cap", 0),
                        "updated_at": datetime.now().isoformat(),
                    }
                ).eq("stock_code", code).execute()
                updated += 1
        except Exception as e:
            logger.debug(f"가격 업데이트 실패 ({code}): {e}")

    logger.info(f"종목 가격 업데이트: {updated}건")
    return updated
