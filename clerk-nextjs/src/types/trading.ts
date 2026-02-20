// ============================================================
// Trading domain types
// ============================================================

/** 종목 기본 정보 */
export interface Stock {
  code: string;
  name: string;
  market: "KOSPI" | "KOSDAQ";
  currentPrice?: number;
  changePrice?: number;
  changeRate?: number;
}

/** OHLCV 캔들 데이터 */
export interface CandleData {
  time: string; // "yyyy-MM-dd" or epoch seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** 거래량 히스토그램 */
export interface VolumeData {
  time: string;
  value: number;
  color: string;
}

/** 실시간 가격 */
export interface PriceData {
  code: string;
  price: number;
  change: number;
  changeRate: number;
  volume: number;
  high: number;
  low: number;
  open: number;
  prevClose: number;
  timestamp: string;
}

/** 호가 단일 레벨 */
export interface OrderbookLevel {
  price: number;
  volume: number;
  accumulatedVolume?: number;
}

/** 호가 데이터 */
export interface OrderbookData {
  asks: OrderbookLevel[]; // 매도 호가 (높은 가격 -> 낮은 가격)
  bids: OrderbookLevel[]; // 매수 호가 (높은 가격 -> 낮은 가격)
}

/** 계좌 정보 */
export interface Account {
  id: string;
  userId: string;
  balance: number;
  initialCapital: number;
  totalAsset: number;
  totalProfit: number;
  totalProfitRate: number;
  createdAt: string;
}

/** 보유 종목 */
export interface Holding {
  stockCode: string;
  stockName: string;
  quantity: number;
  avgPrice: number;
  currentPrice: number;
  totalValue: number;
  profit: number;
  profitRate: number;
}

/** 주문 유형 */
export type OrderSide = "buy" | "sell";
export type OrderType = "market" | "limit";
export type OrderStatus = "pending" | "filled" | "partial" | "cancelled" | "rejected";

/** 주문 */
export interface Order {
  id?: string;
  accountId: string;
  stockCode: string;
  stockName: string;
  side: OrderSide;
  type: OrderType;
  price: number;
  quantity: number;
  filledQuantity?: number;
  filledPrice?: number;
  status?: OrderStatus;
  createdAt?: string;
}

/** 주문 요청 */
export interface PlaceOrderRequest {
  stockCode: string;
  stockName: string;
  side: OrderSide;
  type: OrderType;
  price: number;
  quantity: number;
}

/** 차트 타임프레임 */
export type Timeframe = "1m" | "5m" | "15m" | "1d";

export const TIMEFRAME_LABELS: Record<Timeframe, string> = {
  "1m": "1분",
  "5m": "5분",
  "15m": "15분",
  "1d": "일봉",
};
