"""
모의 체결 엔진

실시간 시세 기반으로 주문을 체결 처리합니다.
- 시장가: 현재가로 즉시 체결
- 지정가: 시장 체결가가 지정가에 도달 시 체결
- 수수료/세금 자동 계산
- 잔고/보유 자동 업데이트
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("trading_engine")

# 수수료/세금 (실제와 동일)
BUY_FEE_RATE = 0.00015    # 매수 수수료 0.015%
SELL_FEE_RATE = 0.00015   # 매도 수수료 0.015%
SELL_TAX_RATE = 0.0018    # 매도 세금 0.18% (증권거래세)

# 가격 제한
LIMIT_RATE = 0.30  # 상한가/하한가 ±30%


def get_tick_size(price: int) -> int:
    """호가 단위 반환."""
    if price < 2000: return 1
    elif price < 5000: return 5
    elif price < 20000: return 10
    elif price < 50000: return 50
    elif price < 200000: return 100
    elif price < 500000: return 500
    else: return 1000


def round_to_tick(price: int) -> int:
    """가격을 호가 단위에 맞게 내림."""
    tick = get_tick_size(price)
    return (price // tick) * tick


class TradingEngine:
    """모의 체결 엔진."""

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._sb = get_supabase_client()
        self._running = False
        self._monitor_task: asyncio.Task | None = None
        # 계좌별 락 (동시 체결 방지)
        self._account_locks: dict[str, asyncio.Lock] = {}
        # 현재 처리 중인 주문 (중복 체결 방지)
        self._processing_orders: set[str] = set()

    async def start(self) -> None:
        """지정가 주문 모니터링 시작."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_pending_orders())
        logger.info("체결 엔진 시작")

    async def stop(self) -> None:
        """체결 엔진 종료."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
        logger.info("체결 엔진 종료")

    def _get_account_lock(self, account_id: str) -> asyncio.Lock:
        """계좌별 락 반환 (없으면 생성)."""
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    # ── 주문 실행 ────────────────────────────────────────────

    async def execute_order(self, order_id: str) -> dict[str, Any]:
        """
        주문 체결 시도.
        - 시장가: 현재가로 즉시 체결
        - 지정가: 현재가가 조건 충족 시 체결, 아니면 대기
        """
        # 중복 처리 방지
        if order_id in self._processing_orders:
            return {"status": "skipped", "reason": "이미 처리 중인 주문"}
        self._processing_orders.add(order_id)

        try:
            # 주문 조회
            result = self._sb.table("orders").select("*").eq("id", order_id).single().execute()
            order = result.data
            if not order:
                raise ValueError(f"주문을 찾을 수 없습니다: {order_id}")

            if order["status"] != "pending":
                return {"status": "skipped", "reason": f"주문 상태: {order['status']}"}

            stock_code = order["stock_code"]
            current_price = await self._get_current_price(stock_code)

            if not current_price or current_price <= 0:
                return {"status": "waiting", "reason": "시세 데이터 없음"}

            if order["order_type"] == "market":
                return await self._fill_order(order, current_price)

            elif order["order_type"] == "limit":
                target_price = order["price"]
                if order["side"] == "buy" and current_price <= target_price:
                    return await self._fill_order(order, target_price)
                elif order["side"] == "sell" and current_price >= target_price:
                    return await self._fill_order(order, target_price)
                return {"status": "waiting", "reason": "지정가 미도달"}

            return {"status": "error", "reason": f"알 수 없는 주문 유형: {order['order_type']}"}
        finally:
            self._processing_orders.discard(order_id)

    async def _fill_order(self, order: dict, fill_price: int) -> dict[str, Any]:
        """주문 체결 처리 (계좌별 락으로 동시성 보호)."""
        order_id = order["id"]
        account_id = order["account_id"]
        stock_code = order["stock_code"]
        stock_name = order.get("stock_name", "")
        side = order["side"]
        quantity = order["quantity"]

        lock = self._get_account_lock(account_id)
        async with lock:
            # 락 획득 후 주문 상태 재확인 (다른 태스크가 먼저 처리했을 수 있음)
            recheck = self._sb.table("orders").select("status").eq("id", order_id).single().execute()
            if recheck.data and recheck.data["status"] != "pending":
                return {"status": "skipped", "reason": "이미 처리된 주문"}

            # 체결가를 호가 단위에 맞춤
            fill_price = round_to_tick(fill_price)
            total_amount = fill_price * quantity

            # 수수료/세금 계산
            if side == "buy":
                fee = int(total_amount * BUY_FEE_RATE)
                tax = 0
                total_cost = total_amount + fee
            else:
                fee = int(total_amount * SELL_FEE_RATE)
                tax = int(total_amount * SELL_TAX_RATE)
                total_cost = total_amount - fee - tax

            # 계좌 조회 (락 내에서 최신 데이터)
            acct_result = self._sb.table("accounts").select("*").eq("id", account_id).single().execute()
            account = acct_result.data
            if not account:
                await self._reject_order(order_id, "계좌를 찾을 수 없습니다")
                return {"status": "rejected", "reason": "계좌 없음"}

            # ── 매수 처리 ────────────────────────────────────────
            if side == "buy":
                if account["balance"] < total_cost:
                    await self._reject_order(order_id, "잔고 부족")
                    return {"status": "rejected", "reason": f"잔고 부족 (필요: {total_cost:,}원, 보유: {account['balance']:,}원)"}

                # 잔고 차감
                new_balance = account["balance"] - total_cost
                self._sb.table("accounts").update({
                    "balance": new_balance,
                    "total_asset": new_balance,
                }).eq("id", account_id).execute()

                # 보유종목 업데이트 (upsert)
                holding_result = (
                    self._sb.table("holdings")
                    .select("*")
                    .eq("account_id", account_id)
                    .eq("stock_code", stock_code)
                    .maybe_single()
                    .execute()
                )

                if holding_result.data:
                    h = holding_result.data
                    old_qty = h["quantity"]
                    old_avg = h["avg_price"]
                    new_qty = old_qty + quantity
                    new_avg = int(((old_avg * old_qty) + (fill_price * quantity)) / new_qty)
                    self._sb.table("holdings").update({
                        "quantity": new_qty,
                        "avg_price": new_avg,
                        "current_price": fill_price,
                        "updated_at": datetime.now().isoformat(),
                    }).eq("id", h["id"]).execute()
                else:
                    self._sb.table("holdings").insert({
                        "account_id": account_id,
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "quantity": quantity,
                        "avg_price": fill_price,
                        "current_price": fill_price,
                    }).execute()

            # ── 매도 처리 ────────────────────────────────────────
            elif side == "sell":
                holding_result = (
                    self._sb.table("holdings")
                    .select("*")
                    .eq("account_id", account_id)
                    .eq("stock_code", stock_code)
                    .maybe_single()
                    .execute()
                )

                if not holding_result.data or holding_result.data["quantity"] < quantity:
                    await self._reject_order(order_id, "보유 수량 부족")
                    return {"status": "rejected", "reason": "보유 수량 부족"}

                h = holding_result.data
                new_qty = h["quantity"] - quantity

                if new_qty == 0:
                    self._sb.table("holdings").delete().eq("id", h["id"]).execute()
                else:
                    self._sb.table("holdings").update({
                        "quantity": new_qty,
                        "current_price": fill_price,
                        "updated_at": datetime.now().isoformat(),
                    }).eq("id", h["id"]).execute()

                # 잔고 증가
                new_balance = account["balance"] + total_cost
                self._sb.table("accounts").update({
                    "balance": new_balance,
                    "total_asset": new_balance,
                }).eq("id", account_id).execute()

            # ── 주문 상태 업데이트 ───────────────────────────────
            self._sb.table("orders").update({
                "status": "filled",
                "filled_quantity": quantity,
                "filled_price": fill_price,
                "filled_at": datetime.now().isoformat(),
            }).eq("id", order_id).execute()

            # ── 거래 내역 기록 ───────────────────────────────────
            self._sb.table("transactions").insert({
                "order_id": order_id,
                "account_id": account_id,
                "stock_code": stock_code,
                "side": side,
                "price": fill_price,
                "quantity": quantity,
                "fee": fee,
                "tax": tax,
            }).execute()

        logger.info(
            f"체결: {side.upper()} {stock_code} {quantity}주 @ {fill_price:,}원 "
            f"(수수료: {fee:,}, 세금: {tax:,})"
        )

        return {
            "status": "filled",
            "fill_price": fill_price,
            "quantity": quantity,
            "fee": fee,
            "tax": tax,
            "total_amount": total_amount,
        }

    async def _reject_order(self, order_id: str, reason: str) -> None:
        """주문 거부."""
        self._sb.table("orders").update({
            "status": "rejected",
        }).eq("id", order_id).execute()
        logger.warning(f"주문 거부 ({order_id}): {reason}")

    # ── 지정가 모니터링 ──────────────────────────────────────

    async def _monitor_pending_orders(self) -> None:
        """미체결 지정가 주문을 주기적으로 확인하여 체결 시도."""
        while self._running:
            try:
                await asyncio.sleep(2)  # 2초 간격

                # 미체결 지정가 주문 조회
                result = (
                    self._sb.table("orders")
                    .select("id, stock_code, price, side, order_type")
                    .eq("status", "pending")
                    .eq("order_type", "limit")
                    .execute()
                )

                for order in (result.data or []):
                    try:
                        current_price = await self._get_current_price(order["stock_code"])
                        if not current_price:
                            continue

                        should_fill = False
                        if order["side"] == "buy" and current_price <= order["price"]:
                            should_fill = True
                        elif order["side"] == "sell" and current_price >= order["price"]:
                            should_fill = True

                        if should_fill:
                            await self.execute_order(order["id"])
                    except Exception as e:
                        logger.debug(f"주문 모니터링 오류 ({order['id']}): {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"주문 모니터링 루프 오류: {e}")
                await asyncio.sleep(5)

    # ── 현재가 조회 ──────────────────────────────────────────

    async def _get_current_price(self, stock_code: str) -> int | None:
        """Redis에서 현재가 조회."""
        if not self._redis:
            return None
        try:
            cached = await self._redis.get(f"price:{stock_code}")
            if cached:
                data = json.loads(cached)
                return data.get("price")
        except Exception:
            pass
        return None

    # ── 총자산 재계산 ────────────────────────────────────────

    async def recalculate_total_asset(self, account_id: str) -> int:
        """보유종목 평가액 + 현금 잔고 = 총자산 재계산."""
        acct = self._sb.table("accounts").select("balance").eq("id", account_id).single().execute()
        balance = acct.data["balance"]

        holdings = self._sb.table("holdings").select("*").eq("account_id", account_id).execute()
        eval_total = 0
        for h in (holdings.data or []):
            current = await self._get_current_price(h["stock_code"])
            price = current if current else h["current_price"]
            eval_total += price * h["quantity"]

        total_asset = balance + eval_total
        self._sb.table("accounts").update({
            "total_asset": total_asset,
        }).eq("id", account_id).execute()

        return total_asset


# ── 싱글턴 ────────────────────────────────────────────────

_engine: TradingEngine | None = None


def get_trading_engine(redis_client=None) -> TradingEngine:
    global _engine
    if _engine is None:
        _engine = TradingEngine(redis_client)
    return _engine
