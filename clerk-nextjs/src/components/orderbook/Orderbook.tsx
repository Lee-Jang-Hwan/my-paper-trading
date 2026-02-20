"use client";

import { useMemo, useState, useEffect } from "react";
import type { OrderbookLevel } from "@/types/trading";
import { formatPrice, formatNumber, priceColorClass } from "@/lib/format";

// ============================================================
// Orderbook – 호가창 (매도 10단계 / 매수 10단계)
// ============================================================

interface OrderbookProps {
  asks: OrderbookLevel[];
  bids: OrderbookLevel[];
  currentPrice?: number;
  prevClose?: number;
  onPriceClick?: (price: number) => void;
}

export default function Orderbook({
  asks,
  bids,
  currentPrice,
  prevClose,
  onPriceClick,
}: OrderbookProps) {
  // SSR과 클라이언트 간 실시간 데이터 불일치로 인한 hydration mismatch 방지
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  // 누적 거래량 계산
  const asksWithAcc = useMemo(() => {
    // asks는 높은 가격 -> 낮은 가격 순서 (화면 위에서 아래)
    const sorted = [...asks].sort((a, b) => b.price - a.price).slice(0, 10);
    let acc = 0;
    const result = sorted.map((level) => {
      acc += level.volume;
      return { ...level, accumulatedVolume: acc };
    });
    // 누적은 가격이 높은 쪽부터
    return result;
  }, [asks]);

  const bidsWithAcc = useMemo(() => {
    const sorted = [...bids].sort((a, b) => b.price - a.price).slice(0, 10);
    let acc = 0;
    return sorted.map((level) => {
      acc += level.volume;
      return { ...level, accumulatedVolume: acc };
    });
  }, [bids]);

  // 최대 거래량 (바 비율 계산용)
  const maxVolume = useMemo(() => {
    const allVolumes = [...asks, ...bids].map((l) => l.volume);
    return Math.max(...allVolumes, 1);
  }, [asks, bids]);

  const change = currentPrice && prevClose ? currentPrice - prevClose : 0;

  if (!mounted) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <div className="grid grid-cols-3 border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>호가</span>
          <span className="text-right">잔량</span>
          <span className="text-right">누적</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* 헤더 */}
      <div className="grid grid-cols-3 border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
        <span>호가</span>
        <span className="text-right">잔량</span>
        <span className="text-right">누적</span>
      </div>

      {/* 매도 호가 (빨간 배경, 위에서 아래로 가격 내림차순) */}
      <div className="flex-1 overflow-y-auto">
        <div className="flex flex-col">
          {asksWithAcc.map((level) => {
            const barWidth = (level.volume / maxVolume) * 100;
            const priceChange = prevClose ? level.price - prevClose : 0;
            return (
              <div
                key={`ask-${level.price}`}
                className="group relative grid cursor-pointer grid-cols-3 items-center px-3 py-1 transition-colors hover:bg-red-500/10"
                onClick={() => onPriceClick?.(level.price)}
              >
                {/* 잔량 바 배경 */}
                <div
                  className="absolute right-0 top-0 h-full bg-red-500/8"
                  style={{ width: `${barWidth}%` }}
                />
                <span
                  className={`relative z-10 text-xs font-medium tabular-nums ${priceColorClass(priceChange)}`}
                >
                  {formatPrice(level.price)}
                </span>
                <span className="relative z-10 text-right text-xs tabular-nums text-red-400">
                  {formatNumber(level.volume)}
                </span>
                <span className="relative z-10 text-right text-xs tabular-nums text-muted-foreground">
                  {formatNumber(level.accumulatedVolume)}
                </span>
              </div>
            );
          })}
        </div>

        {/* 현재가 영역 */}
        <div
          className="border-y border-border bg-muted/50 px-3 py-2"
          onClick={() => currentPrice && onPriceClick?.(currentPrice)}
        >
          <div className="flex items-center justify-between">
            <span className={`text-sm font-bold tabular-nums ${priceColorClass(change)}`}>
              {formatPrice(currentPrice)}
            </span>
            <div className="flex items-center gap-2">
              <span className={`text-xs tabular-nums ${priceColorClass(change)}`}>
                {change > 0 ? "+" : ""}
                {formatPrice(change)}
              </span>
              <span className={`text-xs tabular-nums ${priceColorClass(change)}`}>
                ({change !== 0 && prevClose
                  ? `${change > 0 ? "+" : ""}${((change / prevClose) * 100).toFixed(2)}%`
                  : "0.00%"})
              </span>
            </div>
          </div>
        </div>

        {/* 매수 호가 (파란 배경) */}
        <div className="flex flex-col">
          {bidsWithAcc.map((level) => {
            const barWidth = (level.volume / maxVolume) * 100;
            const priceChange = prevClose ? level.price - prevClose : 0;
            return (
              <div
                key={`bid-${level.price}`}
                className="group relative grid cursor-pointer grid-cols-3 items-center px-3 py-1 transition-colors hover:bg-blue-500/10"
                onClick={() => onPriceClick?.(level.price)}
              >
                {/* 잔량 바 배경 */}
                <div
                  className="absolute right-0 top-0 h-full bg-blue-500/8"
                  style={{ width: `${barWidth}%` }}
                />
                <span
                  className={`relative z-10 text-xs font-medium tabular-nums ${priceColorClass(priceChange)}`}
                >
                  {formatPrice(level.price)}
                </span>
                <span className="relative z-10 text-right text-xs tabular-nums text-blue-400">
                  {formatNumber(level.volume)}
                </span>
                <span className="relative z-10 text-right text-xs tabular-nums text-muted-foreground">
                  {formatNumber(level.accumulatedVolume)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
