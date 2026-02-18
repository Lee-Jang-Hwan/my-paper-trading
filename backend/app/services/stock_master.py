"""
종목 마스터 데이터 관리

KOSPI/KOSDAQ 전체 종목 목록을 1일 1회 수집하여 Supabase에 저장합니다.
"""

import logging
from datetime import datetime

from app.db.supabase_client import get_supabase_client
from app.services.kis_api import get_kis_client

logger = logging.getLogger("stock_master")

# 주요 종목 리스트 (초기 시드 데이터) — KOSPI 50 + KOSDAQ 30 = 80종목
MAJOR_STOCKS = [
    # ── KOSPI 시가총액 상위 ──
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
    ("207940", "삼성바이오로직스", "KOSPI", "바이오"),
    ("005490", "POSCO홀딩스", "KOSPI", "철강"),
    ("028260", "삼성물산", "KOSPI", "지주"),
    ("012330", "현대모비스", "KOSPI", "자동차부품"),
    ("066570", "LG전자", "KOSPI", "전자"),
    ("034730", "SK", "KOSPI", "지주"),
    ("003550", "LG", "KOSPI", "지주"),
    ("055550", "신한지주", "KOSPI", "금융"),
    ("105560", "KB금융", "KOSPI", "금융"),
    ("086790", "하나금융지주", "KOSPI", "금융"),
    ("316140", "우리금융지주", "KOSPI", "금융"),
    ("032830", "삼성생명", "KOSPI", "보험"),
    ("030200", "KT", "KOSPI", "통신"),
    ("017670", "SK텔레콤", "KOSPI", "통신"),
    ("036570", "엔씨소프트", "KOSPI", "게임"),
    ("251270", "넷마블", "KOSPI", "게임"),
    ("259960", "크래프톤", "KOSPI", "게임"),
    ("003670", "포스코퓨처엠", "KOSPI", "소재"),
    ("096770", "SK이노베이션", "KOSPI", "에너지"),
    ("010130", "고려아연", "KOSPI", "비철금속"),
    ("009150", "삼성전기", "KOSPI", "전자부품"),
    ("000810", "삼성화재", "KOSPI", "보험"),
    ("018260", "삼성에스디에스", "KOSPI", "IT서비스"),
    ("011200", "HMM", "KOSPI", "해운"),
    ("033780", "KT&G", "KOSPI", "식품"),
    ("010950", "S-Oil", "KOSPI", "정유"),
    ("034020", "두산에너빌리티", "KOSPI", "에너지"),
    ("009540", "한국조선해양", "KOSPI", "조선"),
    ("329180", "HD현대중공업", "KOSPI", "조선"),
    ("042660", "한화오션", "KOSPI", "조선"),
    ("138040", "메리츠금융지주", "KOSPI", "금융"),
    ("003490", "대한항공", "KOSPI", "항공"),
    ("004020", "현대제철", "KOSPI", "철강"),
    ("011170", "롯데케미칼", "KOSPI", "화학"),
    ("006800", "미래에셋증권", "KOSPI", "증권"),
    ("047050", "포스코인터내셔널", "KOSPI", "무역"),
    ("323410", "카카오뱅크", "KOSPI", "금융"),
    ("352820", "하이브", "KOSPI", "엔터"),
    ("041510", "에스엠", "KOSPI", "엔터"),
    ("035900", "JYP Ent.", "KOSPI", "엔터"),
    # ── KOSDAQ 시가총액 상위 ──
    ("247540", "에코프로비엠", "KOSDAQ", "2차전지"),
    ("086520", "에코프로", "KOSDAQ", "2차전지"),
    ("403870", "HPSP", "KOSDAQ", "반도체장비"),
    ("293490", "카카오게임즈", "KOSDAQ", "게임"),
    ("328130", "루닛", "KOSDAQ", "AI/의료"),
    ("145020", "휴젤", "KOSDAQ", "바이오"),
    ("196170", "알테오젠", "KOSDAQ", "바이오"),
    ("067160", "아프리카TV", "KOSDAQ", "인터넷"),
    ("039030", "이오테크닉스", "KOSDAQ", "반도체장비"),
    ("058470", "리노공업", "KOSDAQ", "반도체장비"),
    ("377300", "카카오페이", "KOSDAQ", "핀테크"),
    ("041190", "우리기술투자", "KOSDAQ", "금융"),
    ("263750", "펄어비스", "KOSDAQ", "게임"),
    ("112040", "위메이드", "KOSDAQ", "게임"),
    ("095340", "ISC", "KOSDAQ", "반도체장비"),
    ("036930", "주성엔지니어링", "KOSDAQ", "반도체장비"),
    ("257720", "실리콘투", "KOSDAQ", "유통"),
    ("240810", "원익IPS", "KOSDAQ", "반도체장비"),
    ("068760", "셀트리온제약", "KOSDAQ", "바이오"),
    ("215600", "신라젠", "KOSDAQ", "바이오"),
    ("140860", "파크시스템스", "KOSDAQ", "반도체장비"),
    ("298380", "에이비엘바이오", "KOSDAQ", "바이오"),
    ("078600", "대주전자재료", "KOSDAQ", "2차전지"),
    ("357780", "솔브레인", "KOSDAQ", "반도체소재"),
    ("122870", "와이지엔터테인먼트", "KOSDAQ", "엔터"),
    ("099190", "아이센스", "KOSDAQ", "의료기기"),
    ("060310", "3S", "KOSDAQ", "2차전지"),
    ("348210", "넥스틴", "KOSDAQ", "반도체장비"),
    ("035760", "CJ ENM", "KOSDAQ", "엔터"),
    ("090460", "비에이치", "KOSDAQ", "전자부품"),
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
