"use client";

import { useAuth } from "@clerk/nextjs";
import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { getAccount, getOrders, cancelOrder } from "@/services/api";
import { formatPrice } from "@/lib/format";
import type { Order, OrderStatus } from "@/types/trading";

const STATUS_TABS: { label: string; value: OrderStatus | "all" }[] = [
  { label: "전체", value: "all" },
  { label: "체결완료", value: "filled" },
  { label: "대기중", value: "pending" },
  { label: "부분체결", value: "partial" },
  { label: "취소", value: "cancelled" },
];

function statusBadge(status?: OrderStatus) {
  switch (status) {
    case "filled":
      return (
        <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-emerald-500/20 text-emerald-400">
          체결
        </span>
      );
    case "partial":
      return (
        <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-amber-500/20 text-amber-400">
          부분체결
        </span>
      );
    case "cancelled":
      return (
        <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-zinc-500/20 text-zinc-400">
          취소
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-blue-500/20 text-blue-400">
          대기
        </span>
      );
  }
}

function formatDate(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:${mi}`;
}

export default function OrdersPage() {
  const { getToken } = useAuth();

  const [loading, setLoading] = useState(true);
  const [orders, setOrders] = useState<Order[]>([]);
  const [accountId, setAccountId] = useState<string | null>(null);
  const [filter, setFilter] = useState<OrderStatus | "all">("all");
  const [cancelling, setCancelling] = useState<string | null>(null);

  const loadOrders = useCallback(async () => {
    try {
      const token = await getToken();
      const acct = await getAccount(token);
      if (!acct) {
        setOrders([]);
        setLoading(false);
        return;
      }
      setAccountId(acct.id);
      const items = await getOrders(token, acct.id);
      setOrders(items);
    } catch {
      setOrders([]);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    loadOrders();
  }, [loadOrders]);

  const handleCancel = useCallback(
    async (orderId: string) => {
      if (!orderId) return;
      setCancelling(orderId);
      try {
        const token = await getToken();
        await cancelOrder(token, orderId);
        toast.success("주문이 취소되었습니다");
        await loadOrders();
      } catch (err) {
        toast.error("주문 취소 실패", {
          description: err instanceof Error ? err.message : "알 수 없는 오류",
        });
      } finally {
        setCancelling(null);
      }
    },
    [getToken, loadOrders]
  );

  const filtered =
    filter === "all" ? orders : orders.filter((o) => o.status === filter);

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-sm text-muted-foreground">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">주문 내역</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            전체 {orders.length}건
          </p>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-1 rounded-lg border border-border bg-card p-1">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setFilter(tab.value)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === tab.value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Orders Table */}
      {filtered.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="px-4 py-3 text-left font-medium">일시</th>
                <th className="px-4 py-3 text-left font-medium">종목</th>
                <th className="px-4 py-3 text-center font-medium">구분</th>
                <th className="px-4 py-3 text-center font-medium">유형</th>
                <th className="px-4 py-3 text-right font-medium">수량</th>
                <th className="px-4 py-3 text-right font-medium">가격</th>
                <th className="px-4 py-3 text-right font-medium">주문금액</th>
                <th className="px-4 py-3 text-center font-medium">상태</th>
                <th className="px-4 py-3 text-center font-medium">작업</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((o, idx) => (
                <tr
                  key={o.id ?? idx}
                  className="border-b border-border/50 transition-colors hover:bg-muted/20"
                >
                  <td className="px-4 py-3 tabular-nums text-muted-foreground">
                    {formatDate(o.createdAt)}
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-medium text-foreground">
                      {o.stockName || o.stockCode}
                    </span>
                    {o.stockName && (
                      <span className="ml-1 text-muted-foreground">
                        {o.stockCode}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span
                      className={`inline-flex h-5 w-8 items-center justify-center rounded text-[10px] font-bold ${
                        o.side === "buy"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-blue-500/20 text-blue-400"
                      }`}
                    >
                      {o.side === "buy" ? "매수" : "매도"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center text-muted-foreground">
                    {o.type === "market" ? "시장가" : "지정가"}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-foreground">
                    {o.quantity.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-foreground">
                    {formatPrice(o.price)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-foreground">
                    {formatPrice(o.price * o.quantity)}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {statusBadge(o.status)}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {o.status === "pending" && o.id && (
                      <button
                        onClick={() => handleCancel(o.id!)}
                        disabled={cancelling === o.id}
                        className="rounded px-2 py-1 text-[10px] font-medium text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                      >
                        {cancelling === o.id ? "취소중..." : "취소"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex h-48 items-center justify-center rounded-lg border border-border bg-card">
          <p className="text-sm text-muted-foreground">
            {filter === "all"
              ? "주문 내역이 없습니다"
              : `'${STATUS_TABS.find((t) => t.value === filter)?.label}' 상태의 주문이 없습니다`}
          </p>
        </div>
      )}
    </div>
  );
}
