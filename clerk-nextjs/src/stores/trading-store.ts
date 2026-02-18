import { create } from "zustand";
import type {
  Stock,
  PriceData,
  OrderbookData,
  Account,
  Holding,
  Order,
} from "@/types/trading";

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
  setAuthToken: (token: string | null) => void;
  connectWs: (stockCode: string) => void;
  disconnectWs: () => void;
}

/**
 * WebSocket URL: Next.js rewrites don't proxy WebSocket.
 * Connect directly to backend.
 */
function getWsBaseUrl(): string {
  if (typeof window === "undefined") return "";

  // NEXT_PUBLIC_WS_URL이 설정된 경우 사용
  const envWs = (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_WS_URL) || "";
  if (envWs) return envWs;

  // 개발환경: backend는 같은 호스트의 8000 포트
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const hostname = window.location.hostname;

  // 프로덕션에서는 같은 호스트 (reverse proxy 사용)
  if (window.location.port === "3000") {
    // 개발환경: Next.js 3000 → FastAPI 8000
    return `${protocol}://${hostname}:8000`;
  }

  // 프로덕션: 같은 호스트로 접속
  return `${protocol}://${window.location.host}`;
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
  _authToken: null as string | null,

  /* ---- setters ---- */
  setSelectedStock: (stock) => {
    const prev = get().selectedStock;
    set({ selectedStock: stock });

    // 종목 변경 시 WebSocket 재연결
    if (stock && stock.code !== prev?.code) {
      const ws = get()._ws;
      if (ws && ws.readyState === WebSocket.OPEN) {
        // 이미 연결되어 있으면 구독만 변경
        ws.send(JSON.stringify({ action: "subscribe", stock_codes: [stock.code] }));
      } else {
        get().disconnectWs();
        get().connectWs(stock.code);
      }
    } else if (!stock) {
      get().disconnectWs();
    }
  },

  setStocks: (stocks) => set({ stocks }),
  setCurrentPrice: (currentPrice) => set({ currentPrice }),
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

  setAuthToken: (token) => set({ _authToken: token } as Partial<TradingState>),

  /* ---- WebSocket ---- */
  connectWs: (stockCode: string) => {
    if (typeof window === "undefined") return;

    const authToken = (get() as unknown as { _authToken: string | null })._authToken;
    if (!authToken) return; // 인증 토큰 없으면 연결하지 않음

    // 재연결 타이머 취소
    const timer = get()._reconnectTimer;
    if (timer) {
      clearTimeout(timer);
      set({ _reconnectTimer: null });
    }

    const prev = get()._ws;

    // 이미 연결되어 있으면 구독만 변경
    if (prev && prev.readyState === WebSocket.OPEN) {
      prev.send(JSON.stringify({ action: "subscribe", stock_codes: [stockCode] }));
      return;
    }

    // 이전 연결 정리
    if (prev) {
      set({ _intentionalClose: true });
      prev.close();
      set({ _ws: null });
    }

    try {
      const wsBase = getWsBaseUrl();
      const wsUrl = `${wsBase}/ws/realtime?token=${encodeURIComponent(authToken)}`;
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        set({ wsConnected: true, _ws: ws, _intentionalClose: false });
        // 연결 후 종목 구독
        ws.send(JSON.stringify({ action: "subscribe", stock_codes: [stockCode] }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === "price_update" && data.data) {
            const d = data.data;
            const selected = get().selectedStock;
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
            const current = get().selectedStock;
            if (current) get().connectWs(current.code);
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
