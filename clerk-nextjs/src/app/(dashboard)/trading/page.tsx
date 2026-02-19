"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import { useTradingStore } from "@/stores/trading-store";
import type { PlaceOrderRequest, Timeframe, CandleData } from "@/types/trading";
import {
  formatPrice,
  formatChange,
  formatPercent,
  formatNumber,
  priceColorClass,
} from "@/lib/format";
import {
  SAMPLE_STOCKS,
  SAMPLE_PRICE,
  SAMPLE_ACCOUNT,
  candlesToVolume,
} from "@/lib/sample-data";
import {
  getStocks,
  getAccount,
  createAccount,
  getHoldings as getHoldingsApi,
  placeOrder as placeOrderApi,
  getCandles,
  getPrice,
} from "@/services/api";

import { toast } from "sonner";
import StockList from "@/components/trading/StockList";
import OrderPanel from "@/components/trading/OrderPanel";
import Orderbook from "@/components/orderbook/Orderbook";
import AgentWorld from "@/components/agents/AgentWorld";

import { useAuth } from "@clerk/nextjs";

// 차트는 SSR에서 window 접근 문제를 방지하기 위해 dynamic import
const StockChart = dynamic(() => import("@/components/chart/StockChart"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
      차트 로딩 중...
    </div>
  ),
});

// ============================================================
// Bottom Tabs: 호가 / AI 에이전트
// ============================================================

function BottomTabs({
  orderbook,
  currentPrice,
  onPriceClick,
  token,
}: {
  orderbook: { asks: { price: number; volume: number }[]; bids: { price: number; volume: number }[] };
  currentPrice: { price: number; prevClose: number };
  onPriceClick: (price: number) => void;
  token: string | null;
}) {
  const [tab, setTab] = useState<"orderbook" | "agents">("orderbook");

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 border-b border-border">
        <button
          onClick={() => setTab("orderbook")}
          className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors ${
            tab === "orderbook"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          호가창
        </button>
        <button
          onClick={() => setTab("agents")}
          className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors ${
            tab === "agents"
              ? "border-b-2 border-primary text-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          AI 에이전트
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "orderbook" ? (
          <Orderbook
            asks={orderbook.asks}
            bids={orderbook.bids}
            currentPrice={currentPrice.price}
            prevClose={currentPrice.prevClose}
            onPriceClick={onPriceClick}
          />
        ) : (
          <AgentWorld token={token} />
        )}
      </div>
    </div>
  );
}

// ============================================================
// Trading Page
// ============================================================

export default function TradingPage() {
  const { getToken } = useAuth();
  const [token, setToken] = useState<string | null>(null);
  const [apiReady, setApiReady] = useState(false);

  const {
    selectedStock,
    setSelectedStock,
    account,
    setAccount,
    holdings,
    setHoldings,
    addOrder,
    currentPrice: livePrice,
    wsConnected,
    setAuthToken,
  } = useTradingStore();

  // 토큰 갱신 + WebSocket 인증 토큰 설정
  useEffect(() => {
    getToken().then((t) => {
      setToken(t);
      setAuthToken(t);
      setApiReady(true);
    });
  }, [getToken, setAuthToken]);

  // API에서 종목 목록 로드 (샘플 데이터 폴백)
  const [stocks, setStocks] = useState(SAMPLE_STOCKS);

  useEffect(() => {
    if (!apiReady) return;
    getStocks(token)
      .then((data) => {
        if (data && data.length > 0) {
          setStocks(data);
        }
      })
      .catch(() => {
        // 실패 시 샘플 데이터 유지
      });
  }, [apiReady, token]);

  // API에서 계좌+보유종목 로드
  const loadAccountAndHoldings = useCallback(async (t: string) => {
    try {
      let acct = await getAccount(t);
      if (!acct) {
        // 계좌가 없으면 자동 생성
        acct = await createAccount(t, 10_000_000);
      }
      setAccount(acct);

      // 보유종목 로드
      try {
        const portfolio = await getHoldingsApi(t, acct.id);
        if (portfolio.holdings.length > 0) {
          setHoldings(portfolio.holdings);
        }
        // 계좌 최신 정보로 갱신 (포트폴리오 API가 계산된 값 포함)
        setAccount(portfolio.account);
      } catch {
        // 보유종목 조회 실패 시 무시
      }
    } catch {
      // API 실패 시 샘플 계좌 사용
      if (!account) setAccount(SAMPLE_ACCOUNT);
    }
  }, [setAccount, setHoldings, account]);

  useEffect(() => {
    if (!apiReady || !token) return;
    loadAccountAndHoldings(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiReady, token]);

  // 계좌가 없으면 샘플 계좌 사용
  const activeAccount = account ?? SAMPLE_ACCOUNT;
  const activeHoldings = holdings;

  // 선택된 종목에 따른 가격/호가 데이터
  const currentStock = useMemo(
    () => stocks.find((s) => s.code === selectedStock?.code),
    [stocks, selectedStock]
  );

  // 실시간 가격 우선, 없으면 샘플 데이터
  const currentPrice = useMemo(() => {
    if (livePrice && selectedStock && livePrice.code === selectedStock.code) {
      return livePrice;
    }
    if (!currentStock) return SAMPLE_PRICE;
    return {
      ...SAMPLE_PRICE,
      code: currentStock.code,
      price: currentStock.currentPrice ?? SAMPLE_PRICE.price,
      change: currentStock.changePrice ?? SAMPLE_PRICE.change,
      changeRate: currentStock.changeRate ?? SAMPLE_PRICE.changeRate,
      prevClose: (currentStock.currentPrice ?? 71500) - (currentStock.changePrice ?? 500),
    };
  }, [currentStock, livePrice, selectedStock]);

  // 캔들 데이터: API에서 로드
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [candleData, setCandleData] = useState<CandleData[]>([]);
  const [candleLoading, setCandleLoading] = useState(false);
  const candleAbortRef = useRef<AbortController | null>(null);

  // 종목 또는 타임프레임 변경 시 캔들 데이터 로드
  useEffect(() => {
    if (!apiReady || !selectedStock) {
      setCandleData([]);
      return;
    }

    // 이전 요청 취소
    candleAbortRef.current?.abort();
    const abort = new AbortController();
    candleAbortRef.current = abort;

    setCandleLoading(true);
    getCandles(token, selectedStock.code, timeframe, 100)
      .then((data) => {
        if (!abort.signal.aborted) {
          setCandleData(data);
        }
      })
      .catch(() => {
        // API 실패 시 빈 배열 유지 (차트 컴포넌트가 샘플 데이터 폴백)
      })
      .finally(() => {
        if (!abort.signal.aborted) setCandleLoading(false);
      });

    return () => abort.abort();
  }, [apiReady, token, selectedStock?.code, timeframe]);

  const volumes = useMemo(() => candlesToVolume(candleData), [candleData]);

  // 호가 데이터: WebSocket 스토어에서 가져오되, 비어있으면 현재가 기반 임시 호가 생성
  const storeOrderbook = useTradingStore((s) => s.orderbook);
  const orderbook = useMemo(() => {
    if (storeOrderbook.asks.length > 0 || storeOrderbook.bids.length > 0) {
      return storeOrderbook;
    }
    // WebSocket 미연결 시 현재가 기반 임시 호가 생성
    const base = currentPrice.price;
    if (!base || base <= 0) return { asks: [], bids: [] };
    const tick = base >= 100000 ? 500 : base >= 50000 ? 100 : 50;
    const asks = Array.from({ length: 10 }, (_, i) => ({
      price: base + tick * (10 - i),
      volume: Math.round(100 + Math.random() * 2000),
    }));
    const bids = Array.from({ length: 10 }, (_, i) => ({
      price: base - tick * i,
      volume: Math.round(100 + Math.random() * 2000),
    }));
    return { asks, bids };
  }, [storeOrderbook, currentPrice.price]);

  // 종목 선택 시 REST API로 초기 가격 로드 (WebSocket 연결 전)
  useEffect(() => {
    if (!apiReady || !token || !selectedStock) return;

    getPrice(token, selectedStock.code)
      .then((priceData) => {
        if (priceData && priceData.price > 0) {
          useTradingStore.getState().setCurrentPrice(priceData);
        }
      })
      .catch(() => {
        // WebSocket에서 가격이 올 때까지 대기
      });
  }, [apiReady, token, selectedStock?.code]);

  // 보유 종목에서 현재 종목의 수량
  const holdingForStock = useMemo(
    () => activeHoldings.find((h) => h.stockCode === selectedStock?.code),
    [activeHoldings, selectedStock]
  );

  // 종목 선택 핸들러
  const handleSelectStock = useCallback(
    (code: string, name: string) => {
      setSelectedStock({ code, name });
    },
    [setSelectedStock]
  );

  // 호가 클릭 핸들러 -- 가격을 주문 패널에 전달
  const [orderbookClickedPrice, setOrderbookClickedPrice] = useState<number | undefined>();

  const handlePriceClick = useCallback((price: number) => {
    setOrderbookClickedPrice(price);
  }, []);

  // 주문 제출
  const [orderLoading, setOrderLoading] = useState(false);

  const handleSubmitOrder = useCallback(
    async (order: PlaceOrderRequest) => {
      // 실제 API 호출 시도
      if (token && activeAccount.id && !activeAccount.id.startsWith("sample")) {
        setOrderLoading(true);
        try {
          const result = await placeOrderApi(token, {
            ...order,
            accountId: activeAccount.id,
          });
          addOrder({
            id: result.id || `order-${Date.now()}`,
            accountId: activeAccount.id,
            ...order,
            filledQuantity: result.filledQuantity ?? 0,
            status: result.status ?? "pending",
            createdAt: result.createdAt || new Date().toISOString(),
          });
          toast.success(
            `${order.side === "buy" ? "매수" : "매도"} 주문이 ${
              result.status === "filled" ? "체결" : "접수"
            }되었습니다.`,
            { description: `${order.stockName} ${formatNumber(order.quantity)}주 @ ${formatPrice(order.price)}원` }
          );

          // 주문 후 계좌+보유종목 갱신
          loadAccountAndHoldings(token);
        } catch (err) {
          toast.error("주문 실패", {
            description: err instanceof Error ? err.message : "알 수 없는 오류",
          });
        } finally {
          setOrderLoading(false);
        }
      } else {
        // 샘플 모드 (API 미연결)
        addOrder({
          id: `order-${Date.now()}`,
          accountId: activeAccount.id,
          ...order,
          filledQuantity: 0,
          status: "pending",
          createdAt: new Date().toISOString(),
        });
        toast.info(
          `[데모] ${order.side === "buy" ? "매수" : "매도"} 주문이 접수되었습니다.`,
          { description: `${order.stockName} ${formatNumber(order.quantity)}주 @ ${formatPrice(order.price)}원` }
        );
      }
    },
    [activeAccount.id, addOrder, token, loadAccountAndHoldings]
  );

  // 타임프레임 변경
  const handleTimeframeChange = useCallback((tf: Timeframe) => {
    setTimeframe(tf);
  }, []);

  return (
    <div className="flex h-[calc(100vh-4.5rem)] flex-col gap-2">
      {/* 상단 헤더: 종목 정보 + 계좌 잔고 */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2">
        {/* 종목 정보 */}
        <div className="flex items-center gap-4">
          {selectedStock ? (
            <>
              <div>
                <h1 className="text-base font-bold text-foreground">
                  {selectedStock.name}
                </h1>
                <span className="text-xs text-muted-foreground">
                  {selectedStock.code}
                </span>
              </div>
              <div className="flex items-baseline gap-3">
                <span className="text-lg font-bold tabular-nums text-foreground">
                  {formatPrice(currentPrice.price)}
                </span>
                <span
                  className={`text-sm font-medium tabular-nums ${priceColorClass(currentPrice.change)}`}
                >
                  {formatChange(currentPrice.change)}
                </span>
                <span
                  className={`text-sm tabular-nums ${priceColorClass(currentPrice.change)}`}
                >
                  ({formatPercent(currentPrice.changeRate)})
                </span>
              </div>
              <div className="hidden items-center gap-4 text-xs text-muted-foreground sm:flex">
                <span>
                  시가{" "}
                  <span className="tabular-nums text-foreground">
                    {formatPrice(currentPrice.open)}
                  </span>
                </span>
                <span>
                  고가{" "}
                  <span className="tabular-nums text-red-500">
                    {formatPrice(currentPrice.high)}
                  </span>
                </span>
                <span>
                  저가{" "}
                  <span className="tabular-nums text-blue-500">
                    {formatPrice(currentPrice.low)}
                  </span>
                </span>
                <span>
                  거래량{" "}
                  <span className="tabular-nums text-foreground">
                    {formatNumber(currentPrice.volume)}
                  </span>
                </span>
              </div>
            </>
          ) : (
            <div>
              <h1 className="text-base font-bold text-foreground">트레이딩</h1>
              <p className="text-xs text-muted-foreground">
                좌측에서 종목을 선택해주세요
              </p>
            </div>
          )}
        </div>

        {/* 계좌 잔고 + 연결 상태 */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                wsConnected ? "bg-green-400" : apiReady ? "bg-yellow-400" : "bg-gray-500"
              }`}
            />
            <span className="text-muted-foreground">
              {wsConnected ? "실시간" : apiReady ? "API 연결" : "오프라인"}
            </span>
          </div>
          <div className="h-6 w-px bg-border" />
          <div className="text-right">
            <p className="text-muted-foreground">보유현금</p>
            <p className="font-semibold tabular-nums text-foreground">
              {formatPrice(activeAccount.balance)}원
            </p>
          </div>
          <div className="h-6 w-px bg-border" />
          <div className="text-right">
            <p className="text-muted-foreground">총자산</p>
            <p className="font-semibold tabular-nums text-foreground">
              {formatPrice(activeAccount.totalAsset)}원
            </p>
          </div>
        </div>
      </div>

      {/* 3열 레이아웃 */}
      <div className="flex min-h-0 flex-1 flex-col gap-2 lg:flex-row">
        {/* 좌측: 종목 목록 */}
        <div className="w-full shrink-0 overflow-hidden rounded-lg border border-border bg-card lg:w-72">
          <StockList
            stocks={stocks}
            selectedCode={selectedStock?.code}
            onSelect={handleSelectStock}
          />
        </div>

        {/* 중앙: 차트 + 호가 */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
          {/* 차트 영역 */}
          <div className="h-64 shrink-0 overflow-hidden rounded-lg border border-border bg-card lg:h-0 lg:min-h-0 lg:flex-[6]">
            <StockChart
              candleData={candleData}
              volumeData={volumes}
              timeframe={timeframe}
              onTimeframeChange={handleTimeframeChange}
            />
          </div>

          {/* 호가창 + 에이전트 월드 (탭 전환) */}
          <div className="h-64 shrink-0 overflow-hidden rounded-lg border border-border bg-card lg:h-0 lg:min-h-0 lg:flex-[4]">
            <BottomTabs
              orderbook={orderbook}
              currentPrice={currentPrice}
              onPriceClick={handlePriceClick}
              token={token}
            />
          </div>
        </div>

        {/* 우측: 주문 패널 + 보유종목 */}
        <div className="flex w-full shrink-0 flex-col gap-2 lg:w-80">
          {/* 주문 패널 */}
          <div className="overflow-y-auto rounded-lg border border-border bg-card p-4">
            <OrderPanel
              stockCode={selectedStock?.code}
              stockName={selectedStock?.name}
              currentPrice={currentPrice.price}
              availableBalance={activeAccount.balance}
              availableQuantity={holdingForStock?.quantity ?? 0}
              initialPrice={orderbookClickedPrice}
              onSubmitOrder={handleSubmitOrder}
            />
          </div>

          {/* 보유종목 요약 */}
          <div className="overflow-y-auto rounded-lg border border-border bg-card p-3">
            <h3 className="mb-2 text-xs font-semibold text-foreground">
              보유종목
            </h3>
            {activeHoldings.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                보유 종목이 없습니다
              </p>
            ) : (
              <div className="space-y-1.5">
                {activeHoldings.map((h) => (
                  <button
                    key={h.stockCode}
                    onClick={() => handleSelectStock(h.stockCode, h.stockName)}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted ${
                      selectedStock?.code === h.stockCode
                        ? "bg-primary/5 ring-1 ring-primary/20"
                        : ""
                    }`}
                  >
                    <div>
                      <p className="text-xs font-medium text-foreground">
                        {h.stockName}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        {formatNumber(h.quantity)}주 | 평단{" "}
                        {formatPrice(h.avgPrice)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-medium tabular-nums text-foreground">
                        {formatPrice(h.totalValue)}
                      </p>
                      <p
                        className={`text-[10px] tabular-nums ${priceColorClass(h.profit)}`}
                      >
                        {formatChange(h.profit)} (
                        {formatPercent(h.profitRate)})
                      </p>
                    </div>
                  </button>
                ))}

                {/* 총 평가 */}
                <div className="border-t border-border pt-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">총 평가금액</span>
                    <span className="font-semibold tabular-nums text-foreground">
                      {formatPrice(
                        activeHoldings.reduce((sum, h) => sum + h.totalValue, 0)
                      )}
                      원
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">총 손익</span>
                    <span
                      className={`font-semibold tabular-nums ${priceColorClass(
                        activeHoldings.reduce((sum, h) => sum + h.profit, 0)
                      )}`}
                    >
                      {formatChange(
                        activeHoldings.reduce((sum, h) => sum + h.profit, 0)
                      )}
                      원
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
