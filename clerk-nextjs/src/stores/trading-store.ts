import { create } from "zustand";
import type {
  Stock,
  PriceData,
  OrderbookData,
  Account,
  Holding,
  Order,
} from "@/types/trading";
import { getWsBaseUrl } from "@/lib/ws-url";

// ============================================================
// Trading Store – Zustand v5
// ============================================================

interface TradingState {
  /* ---- data ---- */
  selectedStock: { code: string; name: string } | null;
  stocks: Stock[];
  currentPrice: PriceData | null;
  orderbook: OrderbookData;
  account: Account | null;
  holdings: Holding[];
  orders: Order[];

  /* ---- websocket ---- */
  wsConnected: boolean;
  _ws: WebSocket | null;
  _reconnectTimer: ReturnType<typeof setTimeout> | null;
  _intentionalClose: boolean;
  _allCodes: string[]; // 전체 구독 종목 코드

  /* ---- actions ---- */
  setSelectedStock: (stock: { code: string; name: string } | null) => void;
  setStocks: (stocks: Stock[]) => void;
  setCurrentPrice: (price: PriceData | null) => void;
  setOrderbook: (orderbook: OrderbookData) => void;
  setAccount: (account: Account | null) => void;
  setHoldings: (holdings: Holding[]) => void;
  setOrders: (orders: Order[]) => void;
  addOrder: (order: Order) => void;
  updateOrder: (orderId: string, updates: Partial<Order>) => void;

  /* ---- websocket management ---- */
  _tokenGetter: (() => Promise<string | null>) | null;
  setTokenGetter: (fn: (() => Promise<string | null>) | null) => void;
  connectWs: (stockCode?: string, allCodes?: string[]) => void;
  disconnectWs: () => void;
}

export const useTradingStore = create<TradingState>((set, get) => ({
  /* ---- initial data ---- */
  selectedStock: null,
  stocks: [],
  currentPrice: null,
  orderbook: { asks: [], bids: [] },
  account: null,
  holdings: [],
  orders: [],

  /* ---- websocket ---- */
  wsConnected: false,
  _ws: null,
  _reconnectTimer: null,
  _intentionalClose: false,
  _allCodes: [],
  _tokenGetter: null as (() => Promise<string | null>) | null,

  /* ---- setters ---- */
  setSelectedStock: (stock) => {
    const prev = get().selectedStock;
    set({ selectedStock: stock });

    // 종목 변경 시: WS가 없으면 연결, 있으면 구독 추가만
    if (stock && stock.code !== prev?.code) {
      const ws = get()._ws;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        // WS가 없으면 새로 연결 (전체 종목 구독)
        get().connectWs(stock.code, get()._allCodes);
      }
      // WS가 이미 연결되어 있으면 전체 종목이 이미 구독 중이므로 추가 작업 불필요
    }
    // 종목 해제(null) 시에도 WS를 유지하여 전체 종목 가격을 계속 수신
  },

  setStocks: (stocks) => set({ stocks }),
  setCurrentPrice: (currentPrice) => {
    set({ currentPrice });
    // 종목 리스트에도 동기화 (헤더 ↔ 종목 리스트 가격 일치)
    if (currentPrice && currentPrice.price > 0) {
      const stocks = get().stocks;
      const idx = stocks.findIndex((s) => s.code === currentPrice.code);
      if (idx >= 0 && stocks[idx].currentPrice !== currentPrice.price) {
        const updated = [...stocks];
        updated[idx] = {
          ...updated[idx],
          currentPrice: currentPrice.price,
          changePrice: currentPrice.change ?? updated[idx].changePrice,
          changeRate: currentPrice.changeRate ?? updated[idx].changeRate,
        };
        set({ stocks: updated });
      }
    }
  },
  setOrderbook: (orderbook) => set({ orderbook }),
  setAccount: (account) => set({ account }),
  setHoldings: (holdings) => set({ holdings }),
  setOrders: (orders) => set({ orders }),

  addOrder: (order) =>
    set((state) => ({ orders: [order, ...state.orders] })),

  updateOrder: (orderId, updates) =>
    set((state) => ({
      orders: state.orders.map((o) =>
        o.id === orderId ? { ...o, ...updates } : o
      ),
    })),

  setTokenGetter: (fn) => set({ _tokenGetter: fn }),

  /* ---- WebSocket ---- */
  connectWs: (stockCode?: string, allCodes?: string[]) => {
    if (typeof window === "undefined") return;

    const tokenGetter = get()._tokenGetter;
    if (!tokenGetter) return;

    // 전체 구독 코드 저장 (재연결 시 사용)
    if (allCodes && allCodes.length > 0) {
      set({ _allCodes: allCodes });
    }

    // 구독할 전체 종목 코드 결정
    const subscribeCodes = get()._allCodes.length > 0
      ? get()._allCodes
      : (stockCode ? [stockCode] : []);

    // 구독할 종목이 없으면 연결 불필요
    if (subscribeCodes.length === 0) return;

    // 재연결 타이머 취소
    const timer = get()._reconnectTimer;
    if (timer) {
      clearTimeout(timer);
      set({ _reconnectTimer: null });
    }

    const prev = get()._ws;

    // 이미 연결되어 있으면 구독만 추가
    if (prev && prev.readyState === WebSocket.OPEN) {
      prev.send(JSON.stringify({ action: "subscribe", stock_codes: subscribeCodes }));
      return;
    }

    // 이전 연결 정리
    if (prev) {
      set({ _intentionalClose: true });
      prev.close();
      set({ _ws: null });
    }

    // 신선한 토큰으로 WS 연결
    tokenGetter().then((freshToken) => {
      if (!freshToken) return;

      try {
        const wsBase = getWsBaseUrl();
        const wsUrl = `${wsBase}/ws/realtime?token=${encodeURIComponent(freshToken)}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          set({ wsConnected: true, _ws: ws, _intentionalClose: false });
          // 전체 종목 구독
          ws.send(JSON.stringify({ action: "subscribe", stock_codes: subscribeCodes }));
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);

            if (data.type === "price_update" && data.data) {
              const d = data.data;
              const selected = get().selectedStock;

              // 1) 선택된 종목이면 currentPrice 업데이트 (헤더 표시용)
              if (selected && d.stock_code === selected.code) {
                set({
                  currentPrice: {
                    code: d.stock_code,
                    price: d.price,
                    change: d.change ?? 0,
                    changeRate: d.change_rate ?? 0,
                    volume: d.volume ?? 0,
                    high: d.high ?? d.price,
                    low: d.low ?? d.price,
                    open: d.open ?? d.price,
                    prevClose: (d.price ?? 0) - (d.change ?? 0),
                    timestamp: d.time ?? new Date().toISOString(),
                  },
                });
              }

              // 2) 종목 리스트의 가격도 업데이트 (모든 종목)
              const stocks = get().stocks;
              if (stocks.length > 0) {
                const idx = stocks.findIndex((s) => s.code === d.stock_code);
                if (idx >= 0) {
                  const updated = [...stocks];
                  updated[idx] = {
                    ...updated[idx],
                    currentPrice: d.price,
                    changePrice: d.change ?? updated[idx].changePrice,
                    changeRate: d.change_rate ?? updated[idx].changeRate,
                  };
                  set({ stocks: updated });
                }
              }

              // 3) 보유종목의 현재가·평가금액·손익도 실시간 반영
              const holdings = get().holdings;
              if (holdings.length > 0) {
                const hIdx = holdings.findIndex((h) => h.stockCode === d.stock_code);
                if (hIdx >= 0) {
                  const h = holdings[hIdx];
                  const newPrice = d.price;
                  const newTotalValue = newPrice * h.quantity;
                  const cost = h.avgPrice * h.quantity;
                  const newProfit = newTotalValue - cost;
                  const newProfitRate = cost > 0 ? Math.round((newProfit / cost) * 10000) / 100 : 0;

                  const updatedHoldings = [...holdings];
                  updatedHoldings[hIdx] = {
                    ...h,
                    currentPrice: newPrice,
                    totalValue: newTotalValue,
                    profit: newProfit,
                    profitRate: newProfitRate,
                  };
                  set({ holdings: updatedHoldings });

                  // 계좌 총자산도 재계산
                  const account = get().account;
                  if (account) {
                    const holdingsTotal = updatedHoldings.reduce((sum, item) => sum + item.totalValue, 0);
                    const newTotalAsset = account.balance + holdingsTotal;
                    const newAccountProfit = newTotalAsset - account.initialCapital;
                    const newAccountProfitRate = account.initialCapital > 0
                      ? Math.round((newAccountProfit / account.initialCapital) * 10000) / 100
                      : 0;
                    set({
                      account: {
                        ...account,
                        totalAsset: newTotalAsset,
                        totalProfit: newAccountProfit,
                        totalProfitRate: newAccountProfitRate,
                      },
                    });
                  }
                }
              }

            } else if (data.type === "orderbook_update" && data.data) {
              const d = data.data;
              const selected = get().selectedStock;
              if (selected && d.stock_code === selected.code) {
                set({ orderbook: { asks: d.asks ?? [], bids: d.bids ?? [] } });
              }
            }
          } catch {
            // ignore malformed messages
          }
        };

        ws.onclose = () => {
          set({ wsConnected: false, _ws: null });

          // 의도적 종료가 아닌 경우에만 자동 재연결
          if (!get()._intentionalClose) {
            const reconnectTimer = setTimeout(() => {
              set({ _reconnectTimer: null });
              const codes = get()._allCodes;
              const current = get().selectedStock;
              // 선택된 종목 또는 전체 구독 코드가 있으면 재연결
              if (current || codes.length > 0) {
                get().connectWs(current?.code, codes);
              }
            }, 3000);
            set({ _reconnectTimer: reconnectTimer });
          }
          set({ _intentionalClose: false });
        };

        ws.onerror = () => {
          ws.close();
        };

        set({ _ws: ws, _intentionalClose: false });
      } catch {
        // WebSocket creation failed – silently ignore
      }
    }).catch(() => {
      // token getter failed – silently ignore
    });
  },

  disconnectWs: () => {
    // 재연결 타이머 취소
    const timer = get()._reconnectTimer;
    if (timer) {
      clearTimeout(timer);
      set({ _reconnectTimer: null });
    }

    const ws = get()._ws;
    if (ws) {
      set({ _intentionalClose: true });
      ws.close();
      set({ _ws: null, wsConnected: false });
    }
  },
}));
