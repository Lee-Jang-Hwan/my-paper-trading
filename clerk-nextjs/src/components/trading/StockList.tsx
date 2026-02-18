"use client";

import { useState, useMemo } from "react";
import type { Stock } from "@/types/trading";
import { formatPrice, formatPercent, priceColorClass } from "@/lib/format";

// ============================================================
// StockList – 종목 목록 사이드바
// ============================================================

interface StockListProps {
  stocks: Stock[];
  selectedCode?: string;
  onSelect: (code: string, name: string) => void;
}

export default function StockList({
  stocks,
  selectedCode,
  onSelect,
}: StockListProps) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return stocks;
    const q = search.trim().toLowerCase();
    return stocks.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.code.includes(q)
    );
  }, [stocks, search]);

  return (
    <div className="flex h-full flex-col">
      {/* 검색 */}
      <div className="p-3 pb-2">
        <div className="relative">
          <svg
            className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            viewBox="0 0 24 24"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="종목명 또는 코드 검색"
            className="h-8 w-full rounded-md border border-border bg-background pl-8 pr-3 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
          />
        </div>
      </div>

      {/* 종목 수 */}
      <div className="flex items-center justify-between px-3 pb-1">
        <span className="text-xs text-muted-foreground">
          종목 {filtered.length}개
        </span>
      </div>

      {/* 종목 목록 */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
            검색 결과가 없습니다
          </div>
        ) : (
          <div className="space-y-0.5 px-1.5">
            {filtered.map((stock) => {
              const isSelected = stock.code === selectedCode;
              const changeColor = priceColorClass(stock.changePrice ?? null);

              return (
                <button
                  key={stock.code}
                  onClick={() => onSelect(stock.code, stock.name)}
                  className={`flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left transition-colors ${
                    isSelected
                      ? "bg-primary/10 ring-1 ring-primary/30"
                      : "hover:bg-muted"
                  }`}
                >
                  {/* 왼쪽: 이름 + 코드 */}
                  <div className="min-w-0 flex-1">
                    <p
                      className={`truncate text-xs font-medium ${
                        isSelected ? "text-foreground" : "text-foreground"
                      }`}
                    >
                      {stock.name}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {stock.code}
                    </p>
                  </div>

                  {/* 오른쪽: 가격 + 변동 */}
                  <div className="ml-2 text-right">
                    <p className="text-xs font-medium tabular-nums text-foreground">
                      {formatPrice(stock.currentPrice)}
                    </p>
                    <p className={`text-[10px] tabular-nums ${changeColor}`}>
                      {formatPercent(stock.changeRate)}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
