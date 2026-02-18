import type {
  Stock,
  PriceData,
  CandleData,
  Account,
  Holding,
  Order,
  PlaceOrderRequest,
  OrderStatus,
  Timeframe,
} from "@/types/trading";

// ============================================================
// HTTP API client – uses Clerk auth token passed as parameter
// ============================================================

const BASE = "/api";

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

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }

  return res.json() as Promise<T>;
}

// ---- snake_case ↔ camelCase 변환 ----

function snakeToCamel(s: string): string {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

/** 백엔드 응답(snake_case) → 프론트엔드(camelCase) */
function toCamelCase<T>(obj: unknown): T {
  if (Array.isArray(obj)) return obj.map((item) => toCamelCase(item)) as T;
  if (obj !== null && typeof obj === "object") {
    return Object.fromEntries(
      Object.entries(obj as Record<string, unknown>).map(([k, v]) => [
        snakeToCamel(k),
        v !== null && typeof v === "object" ? toCamelCase(v) : v,
      ])
    ) as T;
  }
  return obj as T;
}

// ---- 종목 ----

export async function getStocks(
  token: string | null,
  search?: string,
  market?: string
): Promise<Stock[]> {
  const params = new URLSearchParams();
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
  _token: string | null,
  _stockCode: string,
  _timeframe: Timeframe = "1d",
  _limit: number = 100
): Promise<CandleData[]> {
  // TODO: 캔들 데이터 API 미구현 — 빈 배열 반환
  return [];
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

export async function placeOrder(
  token: string | null,
  order: PlaceOrderRequest & { accountId: string }
): Promise<Order> {
  const raw = await request<unknown>("/orders", token, {
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
  return toCamelCase<Order>(raw);
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
  return toCamelCase<Order[]>(raw.items);
}

export async function cancelOrder(
  token: string | null,
  orderId: string
): Promise<Order> {
  const raw = await request<unknown>(`/orders/${orderId}`, token, {
    method: "DELETE",
  });
  return toCamelCase<Order>(raw);
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
