"use client";

import { useUser, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { getAccount, createAccount, getHoldings } from "@/services/api";
import { formatPrice, formatPercent, formatChange, priceColorClass } from "@/lib/format";

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
  const [holdingsCount, setHoldingsCount] = useState(0);

  // 계좌 조회
  const loadAccount = useCallback(async () => {
    try {
      const token = await getToken();
      const acct = await getAccount(token);
      if (acct) {
        setAccount(acct);
        // 보유종목 수 조회
        try {
          const portfolio = await getHoldings(token, acct.id);
          setHoldingsCount(portfolio.holdings.length);
        } catch {
          // 보유종목 조회 실패해도 계좌 정보는 표시
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
    if (isLoaded) loadAccount();
  }, [isLoaded, loadAccount]);

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
    <div className="space-y-8">
      {/* Demo Banner */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3">
        <p className="text-xs font-medium text-amber-200">
          모의투자 데모 모드 — 실제 자금이 사용되지 않습니다. 가상 자금으로 안전하게 투자를 연습하세요.
        </p>
      </div>

      {/* Welcome Section */}
      <div className="space-y-2">
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
                모의 투자를 시작하려면 가상 계좌를 만들어주세요. (초기 자금: 1,000만원)
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

      {/* Stats Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* 내 계좌 */}
        <div className="rounded-lg border border-border bg-card p-5">
          <p className="text-xs font-medium text-muted-foreground">보유현금</p>
          <p className="mt-2 text-2xl font-bold text-primary tabular-nums">
            {hasAccount ? `${formatPrice(account.balance)}원` : "---"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {hasAccount ? `초기자금 ${formatPrice(account.initialCapital)}원` : "계좌를 생성해주세요"}
          </p>
        </div>

        {/* 총자산 */}
        <div className="rounded-lg border border-border bg-card p-5">
          <p className="text-xs font-medium text-muted-foreground">총자산</p>
          <p className="mt-2 text-2xl font-bold text-foreground tabular-nums">
            {hasAccount ? `${formatPrice(account.totalAsset)}원` : "---"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {hasAccount
              ? `보유현금 + 평가금액`
              : "계좌를 생성해주세요"}
          </p>
        </div>

        {/* 수익률 */}
        <div className="rounded-lg border border-border bg-card p-5">
          <p className="text-xs font-medium text-muted-foreground">총 손익</p>
          <p className={`mt-2 text-2xl font-bold tabular-nums ${hasAccount ? priceColorClass(account.totalProfit) : "text-foreground"}`}>
            {hasAccount ? `${formatChange(account.totalProfit)}원` : "---"}
          </p>
          <p className={`mt-1 text-xs tabular-nums ${hasAccount ? priceColorClass(account.totalProfitRate) : "text-muted-foreground"}`}>
            {hasAccount ? `${formatPercent(account.totalProfitRate)}` : "계좌를 생성해주세요"}
          </p>
        </div>

        {/* 보유종목 */}
        <div className="rounded-lg border border-border bg-card p-5">
          <p className="text-xs font-medium text-muted-foreground">보유종목</p>
          <p className="mt-2 text-2xl font-bold text-accent tabular-nums">
            {hasAccount ? `${holdingsCount}종목` : "---"}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {hasAccount ? "현재 보유 중인 종목" : "계좌를 생성해주세요"}
          </p>
        </div>
      </div>

      {/* Quick Action */}
      <div className="flex justify-center pt-4">
        <Link
          href="/trading"
          className="inline-flex h-11 items-center justify-center rounded-lg bg-primary px-6 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          트레이딩 시작하기
        </Link>
      </div>
    </div>
  );
}
