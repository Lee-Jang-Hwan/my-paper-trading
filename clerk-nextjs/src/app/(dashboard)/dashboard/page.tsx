"use client";

import { useUser, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useState, useEffect, useCallback, useMemo } from "react";
import { toast } from "sonner";
import {
  getAccount,
  createAccount,
  getHoldings,
  getOrders,
  getAgentWorldState,
} from "@/services/api";
import {
  formatPrice,
  formatPercent,
  formatChange,
  priceColorClass,
} from "@/lib/format";
import type { Holding, Order } from "@/types/trading";
import type { WorldState } from "@/types/agent";
import { AGENT_INFO } from "@/types/agent";
import type { AgentType } from "@/types/agent";
import { DonutChart } from "@/components/dashboard/DonutChart";

export default function DashboardPage() {
  const { user, isLoaded } = useUser();
  const { getToken } = useAuth();

  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [account, setAccount] = useState<{
    id: string;
    balance: number;
    initialCapital: number;
    totalAsset: number;
    totalProfit: number;
    totalProfitRate: number;
  } | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [agentWorld, setAgentWorld] = useState<WorldState | null>(null);

  // 계좌 + 보유종목 + 주문 + 에이전트 조회
  const loadAll = useCallback(async () => {
    try {
      const token = await getToken();
      const acct = await getAccount(token);
      if (acct) {
        setAccount(acct);
        // 병렬 조회 (실시간 가격으로 보유종목 평가)
        const [portfolioRes, ordersRes, agentRes] = await Promise.allSettled([
          getHoldings(token, acct.id, true),
          getOrders(token, acct.id),
          getAgentWorldState(token),
        ]);
        if (portfolioRes.status === "fulfilled") {
          setHoldings(portfolioRes.value.holdings);
        }
        if (ordersRes.status === "fulfilled") {
          setOrders(ordersRes.value.slice(0, 5));
        }
        if (agentRes.status === "fulfilled") {
          setAgentWorld(agentRes.value);
        }
      } else {
        setAccount(null);
      }
    } catch {
      setAccount(null);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    if (isLoaded) loadAll();
  }, [isLoaded, loadAll]);

  // 계좌 생성
  const handleCreateAccount = useCallback(async () => {
    setCreating(true);
    try {
      const token = await getToken();
      const newAcct = await createAccount(token, 10_000_000);
      setAccount(newAcct);
    } catch (err) {
      toast.error("계좌 생성 실패", {
        description: err instanceof Error ? err.message : "알 수 없는 오류",
      });
    } finally {
      setCreating(false);
    }
  }, [getToken]);

  // 도넛 차트 데이터
  const donutData = useMemo(() => {
    if (!account) return [];
    const segments: { label: string; value: number; color: string }[] = [];
    const COLORS = [
      "#3b82f6",
      "#10b981",
      "#f59e0b",
      "#ef4444",
      "#8b5cf6",
      "#ec4899",
      "#06b6d4",
      "#84cc16",
    ];
    holdings.forEach((h, i) => {
      segments.push({
        label: h.stockName,
        value: h.totalValue,
        color: COLORS[i % COLORS.length],
      });
    });
    if (account.balance > 0) {
      segments.push({
        label: "현금",
        value: account.balance,
        color: "#6b7280",
      });
    }
    return segments;
  }, [account, holdings]);

  // 투자금액 계산
  const investedAmount = account
    ? account.totalAsset - account.balance
    : 0;

  if (!isLoaded || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-sm text-muted-foreground">로딩 중...</div>
      </div>
    );
  }

  const displayName = user?.firstName || user?.username || "투자자";
  const hasAccount = account !== null;

  return (
    <div className="space-y-6">
      {/* Demo Banner */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3">
        <p className="text-xs font-medium text-amber-200">
          모의투자 데모 모드 — 실제 자금이 사용되지 않습니다. 가상 자금으로
          안전하게 투자를 연습하세요.
        </p>
      </div>

      {/* Welcome Section */}
      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-foreground">
          안녕하세요, {displayName}님
        </h1>
        <p className="text-sm text-muted-foreground">
          오늘의 투자 현황을 확인하세요.
        </p>
      </div>

      {/* Account Creation Banner */}
      {!hasAccount && (
        <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium text-foreground">
                아직 투자 계좌가 없습니다
              </p>
              <p className="text-xs text-muted-foreground">
                모의 투자를 시작하려면 가상 계좌를 만들어주세요. (초기 자금:
                1,000만원)
              </p>
            </div>
            <button
              onClick={handleCreateAccount}
              disabled={creating}
              className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {creating ? "생성 중..." : "계좌 생성"}
            </button>
          </div>
        </div>
      )}

      {/* ── Stats Cards (5열) ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {/* 총자산 */}
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">총자산</p>
          <p className="mt-1.5 text-xl font-bold text-foreground tabular-nums">
            {hasAccount ? `${formatPrice(account.totalAsset)}` : "---"}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {hasAccount
              ? `초기 ${formatPrice(account.initialCapital)}원`
              : "계좌를 생성해주세요"}
          </p>
        </div>

        {/* 보유현금 */}
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">보유현금</p>
          <p className="mt-1.5 text-xl font-bold text-primary tabular-nums">
            {hasAccount ? `${formatPrice(account.balance)}` : "---"}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {hasAccount
              ? `${((account.balance / account.totalAsset) * 100).toFixed(1)}% 현금비중`
              : ""}
          </p>
        </div>

        {/* 투자금액 */}
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">투자금액</p>
          <p className="mt-1.5 text-xl font-bold text-accent tabular-nums">
            {hasAccount ? `${formatPrice(investedAmount)}` : "---"}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {hasAccount ? `${holdings.length}종목 보유` : ""}
          </p>
        </div>

        {/* 총 손익 */}
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">총 손익</p>
          <p
            className={`mt-1.5 text-xl font-bold tabular-nums ${hasAccount ? priceColorClass(account.totalProfit) : "text-foreground"}`}
          >
            {hasAccount ? `${formatChange(account.totalProfit)}` : "---"}
          </p>
          <p
            className={`mt-0.5 text-[11px] tabular-nums ${hasAccount ? priceColorClass(account.totalProfitRate) : "text-muted-foreground"}`}
          >
            {hasAccount ? formatPercent(account.totalProfitRate) : ""}
          </p>
        </div>

        {/* 수익률 */}
        <div className="col-span-2 rounded-lg border border-border bg-card p-4 sm:col-span-1">
          <p className="text-xs font-medium text-muted-foreground">수익률</p>
          <p
            className={`mt-1.5 text-xl font-bold tabular-nums ${hasAccount ? priceColorClass(account.totalProfitRate) : "text-foreground"}`}
          >
            {hasAccount ? formatPercent(account.totalProfitRate) : "---"}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {hasAccount
              ? `대비 ${formatChange(account.totalProfit)}원`
              : ""}
          </p>
        </div>
      </div>

      {/* ── 포트폴리오 도넛 + 보유종목 테이블 ── */}
      {hasAccount && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* 도넛 차트 */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-foreground">
              포트폴리오 구성
            </h2>
            {donutData.length > 0 ? (
              <DonutChart
                data={donutData}
                totalLabel="총자산"
                totalValue={`${formatPrice(account.totalAsset)}원`}
              />
            ) : (
              <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
                보유종목이 없습니다
              </div>
            )}
          </div>

          {/* 보유종목 테이블 */}
          <div className="rounded-lg border border-border bg-card p-5 lg:col-span-2">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground">
                보유종목
              </h2>
              <Link
                href="/trading"
                className="text-xs text-primary hover:underline"
              >
                트레이딩 →
              </Link>
            </div>
            {holdings.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground">
                      <th className="pb-2 text-left font-medium">종목</th>
                      <th className="pb-2 text-right font-medium">수량</th>
                      <th className="hidden pb-2 text-right font-medium sm:table-cell">
                        평균가
                      </th>
                      <th className="pb-2 text-right font-medium">현재가</th>
                      <th className="pb-2 text-right font-medium">평가금액</th>
                      <th className="pb-2 text-right font-medium">손익률</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.map((h) => (
                      <tr
                        key={h.stockCode}
                        className="border-b border-border/50 transition-colors hover:bg-muted/30"
                      >
                        <td className="py-2.5">
                          <Link
                            href={`/trading?stock=${h.stockCode}`}
                            className="hover:text-primary"
                          >
                            <span className="font-medium text-foreground">
                              {h.stockName}
                            </span>
                            <span className="ml-1 text-muted-foreground">
                              {h.stockCode}
                            </span>
                          </Link>
                        </td>
                        <td className="py-2.5 text-right tabular-nums text-foreground">
                          {h.quantity.toLocaleString()}주
                        </td>
                        <td className="hidden py-2.5 text-right tabular-nums text-muted-foreground sm:table-cell">
                          {formatPrice(h.avgPrice)}
                        </td>
                        <td className="py-2.5 text-right tabular-nums text-foreground">
                          {formatPrice(h.currentPrice)}
                        </td>
                        <td className="py-2.5 text-right tabular-nums text-foreground">
                          {formatPrice(h.totalValue)}
                        </td>
                        <td
                          className={`py-2.5 text-right tabular-nums font-medium ${priceColorClass(h.profitRate)}`}
                        >
                          {formatPercent(h.profitRate)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                보유종목이 없습니다. 트레이딩에서 첫 매수를 해보세요.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 최근 주문 + AI 에이전트 요약 ── */}
      {hasAccount && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* 최근 주문 */}
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground">
                최근 주문
              </h2>
              <Link
                href="/orders"
                className="text-xs text-primary hover:underline"
              >
                전체보기 →
              </Link>
            </div>
            {orders.length > 0 ? (
              <div className="space-y-2">
                {orders.map((o, idx) => (
                  <div
                    key={o.id ?? idx}
                    className="flex items-center justify-between rounded-md border border-border/50 px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex h-5 w-8 items-center justify-center rounded text-[10px] font-bold ${
                          o.side === "buy"
                            ? "bg-red-500/20 text-red-400"
                            : "bg-blue-500/20 text-blue-400"
                        }`}
                      >
                        {o.side === "buy" ? "매수" : "매도"}
                      </span>
                      <span className="text-xs font-medium text-foreground">
                        {o.stockName || o.stockCode}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs tabular-nums">
                      <span className="text-muted-foreground">
                        {o.quantity.toLocaleString()}주
                      </span>
                      <span className="text-foreground">
                        {o.type === "market" && !o.price
                          ? (o.filledPrice ? `${formatPrice(o.filledPrice)}원` : "시장가")
                          : `${formatPrice(o.price)}원`}
                      </span>
                      <span
                        className={`text-[10px] ${
                          o.status === "filled"
                            ? "text-emerald-400"
                            : o.status === "cancelled"
                              ? "text-muted-foreground"
                              : "text-amber-400"
                        }`}
                      >
                        {o.status === "filled"
                          ? "체결"
                          : o.status === "cancelled"
                            ? "취소"
                            : o.status === "partial"
                              ? "부분체결"
                              : "대기"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                주문 내역이 없습니다
              </div>
            )}
          </div>

          {/* AI 에이전트 요약 */}
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground">
                AI 에이전트 현황
              </h2>
              <Link
                href="/agents"
                className="text-xs text-primary hover:underline"
              >
                상세보기 →
              </Link>
            </div>
            {agentWorld ? (
              <div className="space-y-2">
                {agentWorld.agents.map((agent) => {
                  const info =
                    AGENT_INFO[agent.agent_type as AgentType] ?? null;
                  return (
                    <div
                      key={agent.agent_type}
                      className="flex items-start gap-2.5 rounded-md border border-border/50 px-3 py-2"
                    >
                      <span className="mt-0.5 text-base">
                        {info?.emoji ?? "🤖"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-semibold text-foreground">
                            {info?.name ?? agent.name}
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {info?.role ?? ""}
                          </span>
                          {agent.is_in_conversation && (
                            <span className="ml-auto h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                          )}
                        </div>
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">
                          {agent.action_description || "대기 중"}
                        </p>
                      </div>
                    </div>
                  );
                })}
                {/* 에이전트 시스템 상태 */}
                <div className="mt-2 flex items-center gap-3 rounded-md bg-muted/30 px-3 py-1.5 text-[10px] text-muted-foreground">
                  <span>
                    틱 #{agentWorld.tick_count}
                  </span>
                  <span>
                    {agentWorld.running ? "실행 중" : "일시정지"}
                  </span>
                  <span>
                    Gemini {agentWorld.gemini_status.tokens_used.toLocaleString()} tokens
                  </span>
                </div>
              </div>
            ) : (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                에이전트 정보를 불러오는 중...
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 빠른 실행 버튼 ── */}
      <div className="flex flex-wrap justify-center gap-3 pt-2">
        <Link
          href="/trading"
          className="inline-flex h-10 items-center justify-center rounded-lg bg-primary px-5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          트레이딩 시작하기
        </Link>
        <Link
          href="/agents"
          className="inline-flex h-10 items-center justify-center rounded-lg border border-border bg-card px-5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
        >
          AI 에이전트
        </Link>
        <Link
          href="/orders"
          className="inline-flex h-10 items-center justify-center rounded-lg border border-border bg-card px-5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
        >
          주문 내역
        </Link>
      </div>
    </div>
  );
}
