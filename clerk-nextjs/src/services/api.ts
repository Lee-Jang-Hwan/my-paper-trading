import type {
  Stock,
  PriceData,
  CandleData,
  Account,
  Holding,
  Order,
  PlaceOrderRequest,
  OrderSide,
  OrderType,
  OrderStatus,
  Timeframe,
} from "@/types/trading";

// ============================================================
// HTTP API client – uses Clerk auth token passed as parameter
// ============================================================

const BASE = "/api";

// 토큰 갱신 함수 — 페이지에서 등록하면 401 시 자동 재시도에 활용
let _refreshToken: (() => Promise<string | null>) | null = null;

/** 페이지 마운트 시 호출: getToken 함수를 등록 */
export function setApiTokenRefresher(fn: () => Promise<string | null>) {
  _refreshToken = fn;
}

async function request<T>(
  path: string,
  token: string | null,
  options?: RequestInit
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      ...headers,
      ...(options?.headers as Record<string, string> | undefined),
    },
  });

  // 401 토큰 만료 → 1회 재시도
  if (res.status === 401 && _refreshToken) {
    const freshToken = await _refreshToken();
    if (freshToken && freshToken !== token) {
      const retryHeaders: Record<string, string> = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${freshToken}`,
      };
      const retryRes = await fetch(`${BASE}${path}`, {
        ...options,
        headers: {
          ...retryHeaders,
          ...(options?.headers as Record<string, string> | undefined),
        },
      });
      if (!retryRes.ok) {
        const body = await retryRes.text().catch(() => "");
        throw new Error(`API ${retryRes.status}: ${body || retryRes.statusText}`);
      }
      return retryRes.json() as Promise<T>;
    }
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }

  return res.json() as Promise<T>;
}

// ---- 종목 ----

export async function getStocks(
  token: string | null,
  search?: string,
  market?: string
): Promise<Stock[]> {
  const params = new URLSearchParams();
  params.set("page_size", "200");
  if (search) params.set("search", search);
  if (market) params.set("market", market);
  const qs = params.toString();
  const raw = await request<{ items: unknown[]; total: number }>(
    `/market/stocks${qs ? `?${qs}` : ""}`,
    token
  );
  // backend returns stock_code/stock_name, frontend uses code/name
  return (raw.items || []).map((item: unknown) => {
    const d = item as Record<string, unknown>;
    return {
      code: d.stock_code as string,
      name: d.stock_name as string,
      market: ((d.market as string) ?? "KOSPI") as "KOSPI" | "KOSDAQ",
      currentPrice: d.current_price as number | undefined,
      changePrice: d.change_price as number | undefined,
      changeRate: d.change_rate as number | undefined,
    } satisfies Stock;
  });
}

export async function getPrice(
  token: string | null,
  stockCode: string
): Promise<PriceData> {
  const raw = await request<Record<string, unknown>>(
    `/market/price/${stockCode}`,
    token
  );
  return {
    code: (raw.stock_code as string) ?? stockCode,
    price: (raw.current_price as number) ?? 0,
    change: (raw.change_price as number) ?? 0,
    changeRate: (raw.change_rate as number) ?? 0,
    volume: (raw.volume as number) ?? 0,
    high: (raw.high_price as number) ?? 0,
    low: (raw.low_price as number) ?? 0,
    open: (raw.open_price as number) ?? 0,
    prevClose: ((raw.current_price as number) ?? 0) - ((raw.change_price as number) ?? 0),
    timestamp: (raw.cached_at as string) ?? "",
  };
}

export async function getCandles(
  token: string | null,
  stockCode: string,
  timeframe: Timeframe = "1d",
  limit: number = 100
): Promise<CandleData[]> {
  // 5m/15m → 1m 데이터를 가져와서 프론트에서 집계
  const tf = timeframe === "1m" || timeframe === "5m" || timeframe === "15m" ? "1m" : "1d";
  // 5분/15분봉은 원본 1분 데이터가 더 많이 필요
  const fetchLimit = timeframe === "5m" ? limit * 5 : timeframe === "15m" ? limit * 15 : limit;
  const raw = await request<{ time: string; open: number; high: number; low: number; close: number; volume: number }[]>(
    `/market/candles/${stockCode}?timeframe=${tf}&limit=${Math.min(fetchLimit, 200)}`,
    token
  );
  const candles = raw.map((r) => ({
    time: r.time,
    open: r.open,
    high: r.high,
    low: r.low,
    close: r.close,
    volume: r.volume,
  }));

  // 5분봉/15분봉: 1분 데이터 집계
  if ((timeframe === "5m" || timeframe === "15m") && candles.length > 0) {
    const minutes = timeframe === "5m" ? 5 : 15;
    return aggregateMinuteCandles(candles, minutes);
  }

  return candles;
}

/** 1분 캔들을 N분 캔들로 집계 */
function aggregateMinuteCandles(candles: CandleData[], minutes: number): CandleData[] {
  if (candles.length === 0) return [];

  const result: CandleData[] = [];
  for (let i = 0; i < candles.length; i += minutes) {
    const group = candles.slice(i, i + minutes);
    if (group.length === 0) break;
    result.push({
      time: group[0].time, // 구간 시작 시간
      open: group[0].open,
      high: Math.max(...group.map((c) => c.high)),
      low: Math.min(...group.map((c) => c.low)),
      close: group[group.length - 1].close,
      volume: group.reduce((sum, c) => sum + c.volume, 0),
    });
  }
  return result;
}

/** 여러 종목 실시간 가격 배치 조회 (최대 20개) */
export async function getBatchPrices(
  token: string | null,
  codes: string[]
): Promise<{ stockCode: string; currentPrice: number; changePrice?: number; changeRate?: number }[]> {
  if (codes.length === 0) return [];
  const codesStr = codes.slice(0, 20).join(",");
  const raw = await request<{ stock_code: string; current_price: number; change_price?: number; change_rate?: number }[]>(
    `/market/prices?codes=${encodeURIComponent(codesStr)}`,
    token
  );
  return raw.map((r) => ({
    stockCode: r.stock_code,
    currentPrice: r.current_price,
    changePrice: r.change_price,
    changeRate: r.change_rate,
  }));
}

// ---- 장 상태 ----

export interface MarketStatus {
  isOpen: boolean;
  phase: "pre_market" | "open" | "closing_auction" | "closed";
  nextEvent: string;
  nextEventTime: string;
}

export async function getMarketStatus(
  token: string | null
): Promise<MarketStatus> {
  const raw = await request<Record<string, unknown>>("/market/status", token);
  return {
    isOpen: raw.is_open as boolean,
    phase: raw.phase as MarketStatus["phase"],
    nextEvent: raw.next_event as string,
    nextEventTime: raw.next_event_time as string,
  };
}

// ---- 계좌 ----

/** 백엔드 AccountResponse → 프론트엔드 Account 변환 */
function mapAccount(raw: Record<string, unknown>): Account {
  return {
    id: raw.id as string,
    userId: (raw.clerk_user_id as string) ?? "",
    balance: (raw.balance as number) ?? 0,
    initialCapital: (raw.initial_capital as number) ?? 0,
    totalAsset: (raw.total_asset as number) ?? 0,
    totalProfit: (raw.pnl as number) ?? 0,
    totalProfitRate: (raw.pnl_rate as number) ?? 0,
    createdAt: (raw.created_at as string) ?? "",
  };
}

/** 사용자의 모든 계좌 조회 (첫 번째 반환) */
export async function getAccount(
  token: string | null
): Promise<Account | null> {
  const raw = await request<Record<string, unknown>[]>("/account", token);
  if (!raw || raw.length === 0) return null;
  return mapAccount(raw[0]);
}

export async function createAccount(
  token: string | null,
  initialCapital: number = 10_000_000
): Promise<Account> {
  const raw = await request<Record<string, unknown>>("/account", token, {
    method: "POST",
    body: JSON.stringify({ initial_capital: initialCapital }),
  });
  return mapAccount(raw);
}

// ---- 보유종목 ----

export async function getHoldings(
  token: string | null,
  accountId: string
): Promise<{ account: Account; holdings: Holding[] }> {
  const raw = await request<Record<string, unknown>>(`/account/portfolio/${accountId}`, token);
  const acctRaw = raw.account as Record<string, unknown>;
  const holdingsRaw = (raw.holdings as Record<string, unknown>[]) ?? [];

  const account = mapAccount(acctRaw);
  const holdings: Holding[] = holdingsRaw.map((h) => ({
    stockCode: (h.stock_code as string) ?? "",
    stockName: (h.stock_name as string) ?? "",
    quantity: (h.quantity as number) ?? 0,
    avgPrice: (h.avg_price as number) ?? 0,
    currentPrice: (h.current_price as number) ?? 0,
    totalValue: (h.eval_amount as number) ?? 0,
    profit: (h.pnl as number) ?? 0,
    profitRate: (h.pnl_rate as number) ?? 0,
  }));

  return { account, holdings };
}

// ---- 주문 ----

/** 백엔드 주문 응답 → 프론트엔드 Order 변환 */
function mapOrder(raw: Record<string, unknown>): Order {
  return {
    id: raw.id as string,
    accountId: (raw.account_id as string) ?? "",
    stockCode: (raw.stock_code as string) ?? "",
    stockName: (raw.stock_name as string) ?? "",
    side: (raw.side as OrderSide) ?? "buy",
    type: (raw.order_type as OrderType) ?? "limit",
    price: (raw.price as number) ?? 0,
    quantity: (raw.quantity as number) ?? 0,
    filledQuantity: (raw.filled_quantity as number) ?? 0,
    filledPrice: (raw.filled_price as number) ?? 0,
    status: (raw.status as OrderStatus) ?? "pending",
    createdAt: (raw.created_at as string) ?? "",
  };
}

export async function placeOrder(
  token: string | null,
  order: PlaceOrderRequest & { accountId: string }
): Promise<Order> {
  const raw = await request<Record<string, unknown>>("/orders", token, {
    method: "POST",
    body: JSON.stringify({
      account_id: order.accountId,
      stock_code: order.stockCode,
      order_type: order.type,
      order_side: order.side,
      quantity: order.quantity,
      price: order.type === "market" ? null : (order.price || null),
    }),
  });
  return mapOrder(raw);
}

export async function getOrders(
  token: string | null,
  accountId?: string,
  status?: OrderStatus
): Promise<Order[]> {
  const params = new URLSearchParams();
  if (accountId) params.set("account_id", accountId);
  if (status) params.set("status", status);
  const qs = params.toString();
  const raw = await request<{ items: unknown[]; total: number }>(
    `/orders${qs ? `?${qs}` : ""}`,
    token
  );
  return (raw.items || []).map((item) => mapOrder(item as Record<string, unknown>));
}

export async function cancelOrder(
  token: string | null,
  orderId: string
): Promise<Order> {
  const raw = await request<Record<string, unknown>>(`/orders/${orderId}`, token, {
    method: "DELETE",
  });
  return mapOrder(raw);
}

// ---- AI 에이전트 ----

import type {
  AgentType,
  AgentState,
  WorldState,
  AskAgentResponse,
  AgentConversation,
  DebateResponse,
  OpinionSummaryResponse,
} from "@/types/agent";

/** 전체 에이전트 월드 상태 */
export async function getAgentWorldState(
  token: string | null
): Promise<WorldState> {
  return request<WorldState>("/agents/world", token);
}

/** 단일 에이전트 상태 */
export async function getAgentState(
  token: string | null,
  agentType: AgentType
): Promise<AgentState> {
  return request<AgentState>(`/agents/state/${agentType}`, token);
}

/** 에이전트에게 질문 */
export async function askAgent(
  token: string | null,
  agentType: AgentType,
  question: string
): Promise<AskAgentResponse> {
  return request<AskAgentResponse>("/agents/ask", token, {
    method: "POST",
    body: JSON.stringify({ agent_type: agentType, question }),
  });
}

/** 최근 에이전트 대화 목록 */
export async function getAgentConversations(
  token: string | null,
  limit?: number
): Promise<AgentConversation[]> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  const qs = params.toString();
  return request<AgentConversation[]>(
    `/agents/conversations${qs ? `?${qs}` : ""}`,
    token
  );
}

/** 긴급 에이전트 미팅 소집 */
export async function triggerAgentMeeting(
  token: string | null,
  topic?: string
): Promise<{ status: string; topic: string }> {
  return request<{ status: string; topic: string }>("/agents/meeting", token, {
    method: "POST",
    body: JSON.stringify({ topic: topic ?? "" }),
  });
}

/** 에이전트 토론 시작 */
export async function startAgentDebate(
  token: string | null,
  topic: string,
  stockCode?: string,
  stockName?: string
): Promise<DebateResponse> {
  return request<DebateResponse>("/agents/debate", token, {
    method: "POST",
    body: JSON.stringify({
      topic,
      stock_code: stockCode,
      stock_name: stockName,
    }),
  });
}

/** 4개 에이전트 의견 동시 조회 */
export async function getAgentOpinions(
  token: string | null,
  topic: string,
  stockCode?: string
): Promise<OpinionSummaryResponse> {
  return request<OpinionSummaryResponse>("/agents/opinions", token, {
    method: "POST",
    body: JSON.stringify({ topic, stock_code: stockCode }),
  });
}
