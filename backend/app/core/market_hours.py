"""
장 시간 유틸리티

한국 주식시장(KRX) 장 시간 판단 및 상태 반환.
공휴일(KRX 휴장일)을 포함하여 정확한 장 상태를 제공합니다.
"""

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 장 시간 구간 (KST 기준 분)
PRE_MARKET_START = 8 * 60 + 30   # 08:30
MARKET_OPEN = 9 * 60              # 09:00
CLOSING_AUCTION = 15 * 60 + 20    # 15:20
MARKET_CLOSE = 15 * 60 + 30       # 15:30

# ── KRX 휴장일 (공휴일 + 대체공휴일 + 임시공휴일) ──────────────
# 매년 12월에 다음 해 목록을 추가하세요.
# 출처: KRX 공시 / 정부 관보
KRX_HOLIDAYS: set[date] = {
    # ── 2025년 ──────────────────────────────────────────────
    date(2025, 1, 1),    # 신정
    date(2025, 1, 28),   # 설날 연휴
    date(2025, 1, 29),   # 설날
    date(2025, 1, 30),   # 설날 연휴
    date(2025, 3, 1),    # 삼일절 (토요일이지만 목록에 포함)
    date(2025, 3, 3),    # 삼일절 대체공휴일
    date(2025, 5, 1),    # 근로자의 날
    date(2025, 5, 5),    # 어린이날
    date(2025, 5, 6),    # 부처님오신날 대체공휴일
    date(2025, 6, 6),    # 현충일
    date(2025, 8, 15),   # 광복절
    date(2025, 10, 3),   # 개천절
    date(2025, 10, 5),   # 추석 연휴
    date(2025, 10, 6),   # 추석
    date(2025, 10, 7),   # 추석 연휴
    date(2025, 10, 8),   # 추석 대체공휴일
    date(2025, 10, 9),   # 한글날
    date(2025, 12, 25),  # 크리스마스
    date(2025, 12, 31),  # 연말 휴장

    # ── 2026년 ──────────────────────────────────────────────
    date(2026, 1, 1),    # 신정
    date(2026, 2, 16),   # 설날 연휴
    date(2026, 2, 17),   # 설날
    date(2026, 2, 18),   # 설날 연휴
    date(2026, 3, 2),    # 삼일절 대체공휴일
    date(2026, 5, 1),    # 근로자의 날
    date(2026, 5, 5),    # 어린이날
    date(2026, 5, 24),   # 부처님오신날 (일요일)
    date(2026, 5, 25),   # 부처님오신날 대체공휴일
    date(2026, 6, 6),    # 현충일 (토요일)
    date(2026, 8, 15),   # 광복절 (토요일)
    date(2026, 8, 17),   # 광복절 대체공휴일
    date(2026, 9, 24),   # 추석 연휴
    date(2026, 9, 25),   # 추석
    date(2026, 9, 26),   # 추석 연휴
    date(2026, 10, 3),   # 개천절 (토요일)
    date(2026, 10, 5),   # 개천절 대체공휴일
    date(2026, 10, 9),   # 한글날
    date(2026, 12, 25),  # 크리스마스
    date(2026, 12, 31),  # 연말 휴장
}


def is_holiday(d: date) -> bool:
    """주어진 날짜가 KRX 휴장일(주말 포함)인지 판단."""
    if d.weekday() >= 5:  # 토/일
        return True
    return d in KRX_HOLIDAYS


def _next_trading_day(d: date) -> date:
    """다음 거래일을 반환합니다."""
    nxt = d + timedelta(days=1)
    while is_holiday(nxt):
        nxt += timedelta(days=1)
    return nxt


def _kst_now() -> datetime:
    return datetime.now(KST)


def is_market_open() -> bool:
    """현재 시각이 장 중(09:00~15:30 KST, 거래일)인지 판단."""
    now = _kst_now()
    if is_holiday(now.date()):
        return False
    t = now.hour * 60 + now.minute
    return MARKET_OPEN <= t < MARKET_CLOSE


def get_market_status() -> dict:
    """
    현재 장 상태를 반환합니다.

    Returns:
        {
            "is_open": bool,
            "phase": "pre_market" | "open" | "closing_auction" | "closed",
            "next_event": str,
            "next_event_time": str (ISO format, KST),
        }
    """
    now = _kst_now()
    today = now.date()
    t = now.hour * 60 + now.minute

    # 다음 거래일 09:00 KST 계산 헬퍼
    def _next_open_dt() -> datetime:
        nxt = _next_trading_day(today)
        return datetime(nxt.year, nxt.month, nxt.day, 9, 0, 0, tzinfo=KST)

    # 휴장일 (주말 + 공휴일)
    if is_holiday(today):
        reason = "공휴일" if today.weekday() < 5 else "주말"
        return {
            "is_open": False,
            "phase": "closed",
            "next_event": "장 시작",
            "next_event_time": _next_open_dt().isoformat(),
            "closed_reason": reason,
        }

    # 장 전
    if t < MARKET_OPEN:
        next_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        phase = "pre_market" if t >= PRE_MARKET_START else "closed"
        return {
            "is_open": False,
            "phase": phase,
            "next_event": "장 시작",
            "next_event_time": next_open.isoformat(),
        }

    # 장 중 (동시호가 전)
    if MARKET_OPEN <= t < CLOSING_AUCTION:
        close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return {
            "is_open": True,
            "phase": "open",
            "next_event": "장 마감",
            "next_event_time": close_time.isoformat(),
        }

    # 동시호가 (15:20~15:30)
    if CLOSING_AUCTION <= t < MARKET_CLOSE:
        close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return {
            "is_open": True,
            "phase": "closing_auction",
            "next_event": "장 마감",
            "next_event_time": close_time.isoformat(),
        }

    # 장 마감 후
    return {
        "is_open": False,
        "phase": "closed",
        "next_event": "장 시작",
        "next_event_time": _next_open_dt().isoformat(),
    }
