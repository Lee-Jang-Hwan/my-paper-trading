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
  generateSampleOrderbook,
} from "@/lib/sample-data";
import {
  getAccount,
  createAccount,
  getHoldings as getHoldingsApi,
  placeOrder as placeOrderApi,
  getCandles,
  getPrice,
  getBatchPrices,
  getMarketStatus,
  setApiTokenRefresher,
} from "@/services/api";
import type { MarketStatus } from "@/services/api";

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
    stocks,
    setStocks,
    account,
    setAccount,
    holdings,
    setHoldings,
    addOrder,
    currentPrice: livePrice,
    wsConnected,
    setTokenGetter,
    connectWs,
  } = useTradingStore();

  // 토큰 갱신 + WebSocket 토큰 getter 설정
  useEffect(() => {
    // tokenGetter: 호출 시마다 신선한 토큰을 가져오는 함수
    setTokenGetter(getToken);
    // API 401 시 자동 재시도를 위한 토큰 갱신 함수 등록
    setApiTokenRefresher(getToken);
    getToken().then((t) => {
      setToken(t);
      setApiReady(true);
    });
  }, [getToken, setTokenGetter]);

  // 장 상태
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);

  // 장 상태 주기적 조회 (30초)
  useEffect(() => {
    if (!apiReady) return;

    const fetchStatus = async () => {
      try {
        const freshToken = await getToken();
        const status = await getMarketStatus(freshToken);
        setMarketStatus(status);
      } catch {
        // 장 상태 조회 실패 시 무시
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [apiReady, getToken]);

  // MVP 10종목 초기화 (스토어에 없으면 설정)
  useEffect(() => {
    if (stocks.length === 0) {
      setStocks(SAMPLE_STOCKS);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 배치 가격 초기 로드 + 전체 종목 WebSocket 구독
  useEffect(() => {
    if (!apiReady) return;

    const allCodes = (stocks.length > 0 ? stocks : SAMPLE_STOCKS).map((s) => s.code);

    // 1) 초기 가격 배치 로드
    const fetchBatchPrices = async () => {
      try {
        if (allCodes.length === 0) return;
        const freshToken = await getToken();
        const prices = await getBatchPrices(freshToken, allCodes);
        if (prices.length === 0) return;
        const priceMap = new Map(
          prices.map((p) => [p.stockCode, p])
        );
        const currentStocks = useTradingStore.getState().stocks;
        const updated = (currentStocks.length > 0 ? currentStocks : SAMPLE_STOCKS).map((stock) => {
          const p = priceMap.get(stock.code);
          if (p) {
            return {
              ...stock,
              currentPrice: p.currentPrice,
              changePrice: p.changePrice,
              changeRate: p.changeRate,
            };
          }
          return stock;
        });
        setStocks(updated);

        // 선택된 종목이면 헤더 가격도 동기화
        const sel = useTradingStore.getState().selectedStock;
        if (sel) {
          const p = priceMap.get(sel.code);
          if (p && p.currentPrice > 0) {
            const prev = useTradingStore.getState().currentPrice;
            // 이미 더 최신 가격이 있으면 덮어쓰지 않음
            if (!prev || prev.price !== p.currentPrice) {
              useTradingStore.getState().setCurrentPrice({
                code: sel.code,
                price: p.currentPrice,
                change: p.changePrice ?? prev?.change ?? 0,
                changeRate: p.changeRate ?? prev?.changeRate ?? 0,
                volume: prev?.volume ?? 0,
                high: prev?.high ?? p.currentPrice,
                low: prev?.low ?? p.currentPrice,
                open: prev?.open ?? p.currentPrice,
                prevClose: p.currentPrice - (p.changePrice ?? 0),
                timestamp: new Date().toISOString(),
              });
            }
          }
        }

        // 보유종목 가격도 배치 가격으로 동기화
        const curHoldings = useTradingStore.getState().holdings;
        if (curHoldings.length > 0) {
          let holdingsChanged = false;
          const updatedHoldings = curHoldings.map((h) => {
            const p = priceMap.get(h.stockCode);
            if (p && p.currentPrice > 0 && p.currentPrice !== h.currentPrice) {
              holdingsChanged = true;
              const newTotalValue = p.currentPrice * h.quantity;
              const cost = h.avgPrice * h.quantity;
              const newProfit = newTotalValue - cost;
              const newProfitRate = cost > 0 ? Math.round((newProfit / cost) * 10000) / 100 : 0;
              return { ...h, currentPrice: p.currentPrice, totalValue: newTotalValue, profit: newProfit, profitRate: newProfitRate };
            }
            return h;
          });
          if (holdingsChanged) {
            useTradingStore.getState().setHoldings(updatedHoldings);
            // 계좌 총자산 재계산
            const acct = useTradingStore.getState().account;
            if (acct) {
              const holdingsTotal = updatedHoldings.reduce((sum, item) => sum + item.totalValue, 0);
              const newTotalAsset = acct.balance + holdingsTotal;
              const newProfit = newTotalAsset - acct.initialCapital;
              const newProfitRate = acct.initialCapital > 0
                ? Math.round((newProfit / acct.initialCapital) * 10000) / 100 : 0;
              useTradingStore.getState().setAccount({
                ...acct, totalAsset: newTotalAsset, totalProfit: newProfit, totalProfitRate: newProfitRate,
              });
            }
          }
        }
      } catch {
        // 배치 가격 조회 실패 시 무시
      }
    };

    // 즉시 1회 실행
    fetchBatchPrices();

    // 2) WebSocket으로 전체 종목 실시간 구독 (종목 미선택이어도 즉시 연결)
    const selected = useTradingStore.getState().selectedStock;
    connectWs(selected?.code, allCodes);

    // 3) WebSocket 폴백: 장 외 시간에는 REST 폴링 유지 (3분 간격)
    const isMarketHoursKST = () => {
      const now = new Date();
      const kstH = (now.getUTCHours() + 9) % 24;
      const kstM = now.getUTCMinutes();
      const day = now.getUTCDay();
      if (day === 0 || day === 6) return false;
      const t = kstH * 60 + kstM;
      return t >= 540 && t <= 930;
    };

    // 장 외: 3분 폴링 / 장 중: WebSocket이 주력이므로 60초 폴백
    const intervalMs = isMarketHoursKST() ? 60000 : 180000;
    const interval = setInterval(fetchBatchPrices, intervalMs);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiReady, getToken]);

  // API에서 계좌+보유종목 로드 (매 호출 시 신선한 토큰 사용)
  const loadAccountAndHoldings = useCallback(async () => {
    try {
      const t = await getToken();
      let acct = await getAccount(t);
      if (!acct) {
        acct = await createAccount(t, 10_000_000);
      }
      setAccount(acct);

      // 보유종목 로드
      try {
        const t2 = await getToken();
        const portfolio = await getHoldingsApi(t2, acct.id);
        if (portfolio.holdings.length > 0) {
          setHoldings(portfolio.holdings);
        }
        setAccount(portfolio.account);
      } catch {
        // 보유종목 조회 실패 시 무시
      }
    } catch {
      if (!account) setAccount(SAMPLE_ACCOUNT);
    }
  }, [setAccount, setHoldings, account, getToken]);

  useEffect(() => {
    if (!apiReady) return;
    loadAccountAndHoldings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiReady]);

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
  const [candleError, setCandleError] = useState<string>("");
  const selectedCodeRef = useRef<string | undefined>(undefined);

  // 종목 또는 타임프레임 변경 시 캔들 데이터 로드
  useEffect(() => {
    const code = selectedStock?.code;
    selectedCodeRef.current = code;

    if (!apiReady || !code) {
      setCandleData([]);
      setCandleError("");
      return;
    }

    setCandleError("");
    let cancelled = false;

    (async () => {
      try {
        const freshToken = await getToken();
        if (cancelled || selectedCodeRef.current !== code) return;

        console.log(`[Chart] Loading candles for ${code} (${timeframe})`);
        const data = await getCandles(freshToken, code, timeframe, 100);
        if (cancelled || selectedCodeRef.current !== code) return;

        if (data && data.length > 0) {
          console.log(`[Chart] Loaded ${data.length} candles for ${code}`);
          setCandleData(data);
          setCandleError("");
        } else {
          console.warn(`[Chart] Empty data for ${code}`);
          setCandleError("차트 데이터가 없습니다");
        }
      } catch (err) {
        if (cancelled || selectedCodeRef.current !== code) return;
        const msg = err instanceof Error ? err.message : "알 수 없는 오류";
        console.error(`[Chart] Error loading ${code}:`, msg);
        setCandleError(msg);
      }
    })();

    return () => { cancelled = true; };
  }, [apiReady, selectedStock?.code, timeframe, getToken]);

  const volumes = useMemo(() => candlesToVolume(candleData), [candleData]);

  // 호가 데이터: WebSocket에서 가져오거나 기본 호가 생성
  const storeOrderbook = useTradingStore((s) => s.orderbook);
  const orderbook = useMemo(() => {
    if (storeOrderbook.asks.length > 0 || storeOrderbook.bids.length > 0) {
      return storeOrderbook;
    }
    return generateSampleOrderbook(currentPrice.price);
  }, [storeOrderbook, currentPrice.price]);

  // 종목 선택 시 REST API로 초기 가격 로드 (WebSocket 연결 전)
  useEffect(() => {
    const code = selectedStock?.code;
    if (!apiReady || !code) return;

    getToken().then((freshToken) => {
      getPrice(freshToken, code)
        .then((priceData) => {
          if (priceData && priceData.price > 0) {
            useTradingStore.getState().setCurrentPrice(priceData);
          }
        })
        .catch((err) => {
          console.error("[Price API Error]", err);
        });
    });
  }, [apiReady, selectedStock?.code, getToken]);

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
      if (apiReady && activeAccount.id && !activeAccount.id.startsWith("sample")) {
        setOrderLoading(true);
        try {
          const freshToken = await getToken();
          const result = await placeOrderApi(freshToken, {
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
            {
              description: order.type === "market"
                ? `${order.stockName} ${formatNumber(order.quantity)}주 (시장가)`
                : `${order.stockName} ${formatNumber(order.quantity)}주 @ ${formatPrice(order.price)}원`,
            }
          );

          // 주문 후 계좌+보유종목 갱신
          loadAccountAndHoldings();
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
    [activeAccount.id, addOrder, apiReady, getToken, loadAccountAndHoldings]
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

        {/* 계좌 잔고 + 연결 상태 + 장 상태 */}
        <div className="flex items-center gap-4 text-xs">
          {/* 장 상태 */}
          {marketStatus && (
            <div className="flex items-center gap-1.5">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  marketStatus.isOpen ? "bg-green-400" : "bg-gray-400"
                }`}
              />
              <span className={marketStatus.isOpen ? "text-green-600 dark:text-green-400 font-medium" : "text-muted-foreground"}>
                {marketStatus.isOpen
                  ? `장 중${marketStatus.phase === "closing_auction" ? " (동시호가)" : ""}`
                  : marketStatus.phase === "pre_market" ? "장 전" : "장 마감"}
              </span>
            </div>
          )}
          {/* WS 연결 상태 */}
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
          <div className="relative h-64 shrink-0 overflow-hidden rounded-lg border border-border bg-card lg:h-0 lg:min-h-0 lg:flex-[6]">
            {/* StockChart를 항상 렌더링 (마운트 유지 → lightweight-charts 초기화 보존) */}
            <StockChart
              candleData={candleData}
              volumeData={volumes}
              timeframe={timeframe}
              onTimeframeChange={handleTimeframeChange}
            />
            {/* 종목 미선택 시 오버레이 */}
            {!selectedStock && (
              <div className="absolute inset-0 flex items-center justify-center bg-card/95">
                <p className="text-sm text-muted-foreground">
                  좌측에서 종목을 선택하면 차트가 표시됩니다
                </p>
              </div>
            )}
            {/* 에러 오버레이 */}
            {selectedStock && candleError && (
              <div className="absolute inset-0 flex items-center justify-center bg-card/80">
                <div className="text-center">
                  <p className="text-sm text-muted-foreground">{candleError}</p>
                  <p className="mt-1 text-xs text-muted-foreground/70">
                    {marketStatus && !marketStatus.isOpen ? "장 마감 후에는 최근 데이터가 제한될 수 있습니다" : "잠시 후 다시 시도해주세요"}
                  </p>
                </div>
              </div>
            )}
            {/* 캔들 정보 배지 */}
            {selectedStock && candleData.length > 0 && (
              <div className="absolute bottom-2 right-2 rounded bg-black/60 px-2 py-1 text-[10px] text-white">
                {candleData.length}개 캔들 | {candleData[0]?.time} ~ {candleData[candleData.length - 1]?.time}
              </div>
            )}
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
              loading={orderLoading}
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
