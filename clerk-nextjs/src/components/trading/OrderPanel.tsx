"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import type { OrderSide, OrderType, PlaceOrderRequest } from "@/types/trading";
import {
  formatPrice,
  formatNumber,
  getTickSize,
  tickUp,
  tickDown,
  roundToTickDown,
} from "@/lib/format";

// ============================================================
// OrderPanel – 매수/매도 주문 패널
// ============================================================

interface OrderPanelProps {
  stockCode?: string;
  stockName?: string;
  currentPrice?: number;
  availableBalance?: number;   // 매수 가능 금액
  availableQuantity?: number;  // 매도 가능 수량
  initialPrice?: number;       // 호가창 클릭 시 전달되는 가격
  onSubmitOrder?: (order: PlaceOrderRequest) => void;
}

const COMMISSION_RATE = 0.00015; // 0.015%
const TAX_RATE = 0.0018;        // 0.18% (매도 시)

export default function OrderPanel({
  stockCode,
  stockName,
  currentPrice = 0,
  availableBalance = 0,
  availableQuantity = 0,
  initialPrice,
  onSubmitOrder,
}: OrderPanelProps) {
  const [side, setSide] = useState<OrderSide>("buy");
  const [orderType, setOrderType] = useState<OrderType>("limit");
  const [price, setPrice] = useState<number>(currentPrice);
  const [quantity, setQuantity] = useState<number>(0);

  // 호가 클릭 시 가격 업데이트
  useEffect(() => {
    if (initialPrice && initialPrice > 0) {
      setPrice(initialPrice);
      setOrderType("limit");
    }
  }, [initialPrice]);

  // 현재가 변경 시 가격 동기화 (지정가 초기값)
  // 사용자가 수동 입력 시에는 유지
  const handleSideChange = useCallback(
    (newSide: OrderSide) => {
      setSide(newSide);
      setQuantity(0);
    },
    []
  );

  // 가격 틱 조절
  const handleTickUp = useCallback(() => {
    setPrice((p) => tickUp(p || currentPrice));
  }, [currentPrice]);

  const handleTickDown = useCallback(() => {
    setPrice((p) => tickDown(p || currentPrice));
  }, [currentPrice]);

  // 수량 퍼센트 선택
  const handlePercentage = useCallback(
    (pct: number) => {
      if (side === "buy") {
        const effectivePrice = orderType === "market" ? currentPrice : price;
        if (effectivePrice > 0) {
          const maxQty = Math.floor(availableBalance / effectivePrice);
          setQuantity(Math.floor(maxQty * pct));
        }
      } else {
        setQuantity(Math.floor(availableQuantity * pct));
      }
    },
    [side, orderType, price, currentPrice, availableBalance, availableQuantity]
  );

  // 주문 금액 계산
  const orderSummary = useMemo(() => {
    const effectivePrice = orderType === "market" ? currentPrice : price;
    const totalAmount = effectivePrice * quantity;
    const commission = Math.round(totalAmount * COMMISSION_RATE);
    const tax = side === "sell" ? Math.round(totalAmount * TAX_RATE) : 0;
    const finalAmount =
      side === "buy"
        ? totalAmount + commission
        : totalAmount - commission - tax;

    return { totalAmount, commission, tax, finalAmount };
  }, [orderType, price, currentPrice, quantity, side]);

  // 주문 제출
  const handleSubmit = useCallback(() => {
    if (!stockCode || !stockName || quantity <= 0) return;

    const effectivePrice = orderType === "market" ? currentPrice : price;
    if (effectivePrice <= 0) return;

    onSubmitOrder?.({
      stockCode,
      stockName,
      side,
      type: orderType,
      price: effectivePrice,
      quantity,
    });

    setQuantity(0);
  }, [stockCode, stockName, side, orderType, price, currentPrice, quantity, onSubmitOrder]);

  const isBuy = side === "buy";
  const isDisabled = !stockCode || quantity <= 0;

  return (
    <div className="flex flex-col gap-4">
      {/* 매수 / 매도 토글 */}
      <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
        <button
          onClick={() => handleSideChange("buy")}
          className={`rounded-md py-2 text-sm font-semibold transition-colors ${
            isBuy
              ? "bg-red-500 text-white shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          매수
        </button>
        <button
          onClick={() => handleSideChange("sell")}
          className={`rounded-md py-2 text-sm font-semibold transition-colors ${
            !isBuy
              ? "bg-blue-500 text-white shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          매도
        </button>
      </div>

      {/* 주문 유형 */}
      <div className="flex gap-2">
        <button
          onClick={() => setOrderType("limit")}
          className={`flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors ${
            orderType === "limit"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:border-foreground/20"
          }`}
        >
          지정가
        </button>
        <button
          onClick={() => setOrderType("market")}
          className={`flex-1 rounded-md border py-1.5 text-xs font-medium transition-colors ${
            orderType === "market"
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:border-foreground/20"
          }`}
        >
          시장가
        </button>
      </div>

      {/* 가격 입력 */}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <label className="text-xs font-medium text-muted-foreground">
            가격
          </label>
          {orderType === "limit" && (
            <span className="text-xs text-muted-foreground">
              호가단위: {formatNumber(getTickSize(price || currentPrice))}원
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleTickDown}
            disabled={orderType === "market"}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border text-sm font-bold text-muted-foreground transition-colors hover:bg-muted disabled:opacity-30"
          >
            -
          </button>
          <input
            type="text"
            value={
              orderType === "market"
                ? "시장가"
                : formatPrice(price || currentPrice)
            }
            onChange={(e) => {
              const num = parseInt(e.target.value.replace(/[^0-9]/g, ""), 10);
              if (!isNaN(num)) {
                setPrice(roundToTickDown(num));
              }
            }}
            disabled={orderType === "market"}
            className="h-9 w-full rounded-md border border-border bg-background px-3 text-center text-sm font-medium tabular-nums text-foreground outline-none transition-colors focus:border-primary disabled:bg-muted disabled:text-muted-foreground"
          />
          <button
            onClick={handleTickUp}
            disabled={orderType === "market"}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border text-sm font-bold text-muted-foreground transition-colors hover:bg-muted disabled:opacity-30"
          >
            +
          </button>
        </div>
      </div>

      {/* 수량 입력 */}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <label className="text-xs font-medium text-muted-foreground">
            수량
          </label>
          <span className="text-xs text-muted-foreground">
            {isBuy
              ? `주문가능: ${formatPrice(availableBalance)}원`
              : `보유수량: ${formatNumber(availableQuantity)}주`}
          </span>
        </div>
        <input
          type="text"
          value={quantity === 0 ? "" : formatNumber(quantity)}
          onChange={(e) => {
            const num = parseInt(e.target.value.replace(/[^0-9]/g, ""), 10);
            setQuantity(isNaN(num) ? 0 : num);
          }}
          placeholder="0"
          className="h-9 w-full rounded-md border border-border bg-background px-3 text-right text-sm font-medium tabular-nums text-foreground outline-none transition-colors focus:border-primary"
        />

        {/* 퍼센트 버튼 */}
        <div className="mt-2 grid grid-cols-4 gap-1">
          {[0.25, 0.5, 0.75, 1].map((pct) => (
            <button
              key={pct}
              onClick={() => handlePercentage(pct)}
              className="rounded-md border border-border py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {pct * 100}%
            </button>
          ))}
        </div>
      </div>

      {/* 주문 요약 */}
      <div className="space-y-1.5 rounded-lg bg-muted/50 p-3">
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">주문금액</span>
          <span className="tabular-nums text-foreground">
            {formatPrice(orderSummary.totalAmount)}원
          </span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">
            수수료 (0.015%)
          </span>
          <span className="tabular-nums text-foreground">
            {formatPrice(orderSummary.commission)}원
          </span>
        </div>
        {!isBuy && (
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">
              세금 (0.18%)
            </span>
            <span className="tabular-nums text-foreground">
              {formatPrice(orderSummary.tax)}원
            </span>
          </div>
        )}
        <div className="border-t border-border pt-1.5">
          <div className="flex justify-between text-xs font-semibold">
            <span className="text-foreground">
              {isBuy ? "총 매수금액" : "총 수령금액"}
            </span>
            <span className={`tabular-nums ${isBuy ? "text-red-500" : "text-blue-500"}`}>
              {formatPrice(orderSummary.finalAmount)}원
            </span>
          </div>
        </div>
      </div>

      {/* 주문 버튼 */}
      <button
        onClick={handleSubmit}
        disabled={isDisabled}
        className={`w-full rounded-lg py-3 text-sm font-bold text-white shadow-sm transition-all disabled:opacity-40 ${
          isBuy
            ? "bg-red-500 hover:bg-red-600 active:bg-red-700"
            : "bg-blue-500 hover:bg-blue-600 active:bg-blue-700"
        }`}
      >
        {isBuy ? "매수" : "매도"} 주문
      </button>
    </div>
  );
}
