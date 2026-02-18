import type {
  Stock,
  CandleData,
  VolumeData,
  PriceData,
  OrderbookData,
  Account,
  Holding,
} from "@/types/trading";

// ============================================================
// Sample / mock data for development & placeholder rendering
// ============================================================

export const SAMPLE_STOCKS: Stock[] = [
  // ── KOSPI ──
  { code: "005930", name: "삼성전자", market: "KOSPI", currentPrice: 71500, changePrice: 500, changeRate: 0.7 },
  { code: "000660", name: "SK하이닉스", market: "KOSPI", currentPrice: 178000, changePrice: -2000, changeRate: -1.11 },
  { code: "373220", name: "LG에너지솔루션", market: "KOSPI", currentPrice: 368500, changePrice: 3500, changeRate: 0.96 },
  { code: "005380", name: "현대차", market: "KOSPI", currentPrice: 232000, changePrice: -1000, changeRate: -0.43 },
  { code: "000270", name: "기아", market: "KOSPI", currentPrice: 125000, changePrice: 1500, changeRate: 1.21 },
  { code: "068270", name: "셀트리온", market: "KOSPI", currentPrice: 185500, changePrice: 0, changeRate: 0 },
  { code: "035420", name: "NAVER", market: "KOSPI", currentPrice: 214500, changePrice: 1500, changeRate: 0.7 },
  { code: "035720", name: "카카오", market: "KOSPI", currentPrice: 43850, changePrice: 350, changeRate: 0.8 },
  { code: "051910", name: "LG화학", market: "KOSPI", currentPrice: 298000, changePrice: 5000, changeRate: 1.71 },
  { code: "006400", name: "삼성SDI", market: "KOSPI", currentPrice: 356000, changePrice: -4000, changeRate: -1.11 },
  { code: "207940", name: "삼성바이오로직스", market: "KOSPI", currentPrice: 820000, changePrice: 5000, changeRate: 0.61 },
  { code: "005490", name: "POSCO홀딩스", market: "KOSPI", currentPrice: 315000, changePrice: -3000, changeRate: -0.94 },
  { code: "028260", name: "삼성물산", market: "KOSPI", currentPrice: 138000, changePrice: 2000, changeRate: 1.47 },
  { code: "012330", name: "현대모비스", market: "KOSPI", currentPrice: 215000, changePrice: -500, changeRate: -0.23 },
  { code: "066570", name: "LG전자", market: "KOSPI", currentPrice: 98500, changePrice: 1000, changeRate: 1.03 },
  { code: "034730", name: "SK", market: "KOSPI", currentPrice: 165000, changePrice: -1500, changeRate: -0.9 },
  { code: "003550", name: "LG", market: "KOSPI", currentPrice: 78500, changePrice: 300, changeRate: 0.38 },
  { code: "055550", name: "신한지주", market: "KOSPI", currentPrice: 51200, changePrice: -200, changeRate: -0.39 },
  { code: "105560", name: "KB금융", market: "KOSPI", currentPrice: 82300, changePrice: 1300, changeRate: 1.61 },
  { code: "086790", name: "하나금융지주", market: "KOSPI", currentPrice: 64000, changePrice: 500, changeRate: 0.79 },
  { code: "030200", name: "KT", market: "KOSPI", currentPrice: 38500, changePrice: -100, changeRate: -0.26 },
  { code: "017670", name: "SK텔레콤", market: "KOSPI", currentPrice: 53000, changePrice: 200, changeRate: 0.38 },
  { code: "259960", name: "크래프톤", market: "KOSPI", currentPrice: 245000, changePrice: 3000, changeRate: 1.24 },
  { code: "036570", name: "엔씨소프트", market: "KOSPI", currentPrice: 178000, changePrice: -2500, changeRate: -1.39 },
  { code: "003670", name: "포스코퓨처엠", market: "KOSPI", currentPrice: 215500, changePrice: 2500, changeRate: 1.17 },
  { code: "096770", name: "SK이노베이션", market: "KOSPI", currentPrice: 112000, changePrice: -1000, changeRate: -0.88 },
  { code: "009150", name: "삼성전기", market: "KOSPI", currentPrice: 145000, changePrice: 2000, changeRate: 1.4 },
  { code: "033780", name: "KT&G", market: "KOSPI", currentPrice: 92000, changePrice: 500, changeRate: 0.55 },
  { code: "329180", name: "HD현대중공업", market: "KOSPI", currentPrice: 155000, changePrice: 4000, changeRate: 2.65 },
  { code: "042660", name: "한화오션", market: "KOSPI", currentPrice: 42000, changePrice: 1500, changeRate: 3.7 },
  { code: "138040", name: "메리츠금융지주", market: "KOSPI", currentPrice: 78000, changePrice: 800, changeRate: 1.04 },
  { code: "003490", name: "대한항공", market: "KOSPI", currentPrice: 24500, changePrice: -200, changeRate: -0.81 },
  { code: "323410", name: "카카오뱅크", market: "KOSPI", currentPrice: 27000, changePrice: 300, changeRate: 1.12 },
  { code: "352820", name: "하이브", market: "KOSPI", currentPrice: 215000, changePrice: -5000, changeRate: -2.27 },
  // ── KOSDAQ ──
  { code: "247540", name: "에코프로비엠", market: "KOSDAQ", currentPrice: 165000, changePrice: 3000, changeRate: 1.85 },
  { code: "086520", name: "에코프로", market: "KOSDAQ", currentPrice: 78000, changePrice: -1200, changeRate: -1.52 },
  { code: "403870", name: "HPSP", market: "KOSDAQ", currentPrice: 42000, changePrice: 800, changeRate: 1.94 },
  { code: "293490", name: "카카오게임즈", market: "KOSDAQ", currentPrice: 18500, changePrice: -300, changeRate: -1.6 },
  { code: "328130", name: "루닛", market: "KOSDAQ", currentPrice: 85000, changePrice: 2500, changeRate: 3.03 },
  { code: "145020", name: "휴젤", market: "KOSDAQ", currentPrice: 185000, changePrice: 1000, changeRate: 0.54 },
  { code: "196170", name: "알테오젠", market: "KOSDAQ", currentPrice: 95000, changePrice: 4000, changeRate: 4.4 },
  { code: "263750", name: "펄어비스", market: "KOSDAQ", currentPrice: 38000, changePrice: -500, changeRate: -1.3 },
  { code: "036930", name: "주성엔지니어링", market: "KOSDAQ", currentPrice: 32000, changePrice: 1200, changeRate: 3.9 },
  { code: "357780", name: "솔브레인", market: "KOSDAQ", currentPrice: 285000, changePrice: -2000, changeRate: -0.7 },
];

/** 삼성전자 기준 60일간 캔들 샘플 */
export function generateSampleCandles(basePrice = 71500, days = 60): CandleData[] {
  const candles: CandleData[] = [];
  let price = basePrice;
  const now = new Date();

  for (let i = days; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    // 주말 건너뛰기
    if (d.getDay() === 0 || d.getDay() === 6) continue;

    const change = (Math.random() - 0.48) * price * 0.03;
    const open = price;
    const close = Math.round(price + change);
    const high = Math.round(Math.max(open, close) + Math.random() * price * 0.01);
    const low = Math.round(Math.min(open, close) - Math.random() * price * 0.01);
    const volume = Math.round(5_000_000 + Math.random() * 15_000_000);

    candles.push({
      time: d.toISOString().slice(0, 10),
      open,
      high,
      low,
      close,
      volume,
    });

    price = close;
  }

  return candles;
}

/** 캔들 데이터에서 볼륨 히스토그램 데이터 생성 */
export function candlesToVolume(candles: CandleData[]): VolumeData[] {
  return candles.map((c) => ({
    time: c.time,
    value: c.volume,
    color: c.close >= c.open ? "rgba(239,68,68,0.5)" : "rgba(59,130,246,0.5)",
  }));
}

/** 삼성전자 기준 현재가 */
export const SAMPLE_PRICE: PriceData = {
  code: "005930",
  price: 71500,
  change: 500,
  changeRate: 0.7,
  volume: 12_345_678,
  high: 72000,
  low: 70800,
  open: 71000,
  prevClose: 71000,
  timestamp: new Date().toISOString(),
};

/** 호가 데이터 생성 */
export function generateSampleOrderbook(basePrice = 71500): OrderbookData {
  const tick = 100; // 삼성전자 호가 단위
  const asks: { price: number; volume: number }[] = [];
  const bids: { price: number; volume: number }[] = [];

  for (let i = 10; i >= 1; i--) {
    asks.push({
      price: basePrice + tick * i,
      volume: Math.round(500 + Math.random() * 5000),
    });
  }

  for (let i = 0; i < 10; i++) {
    bids.push({
      price: basePrice - tick * i,
      volume: Math.round(500 + Math.random() * 5000),
    });
  }

  return { asks, bids };
}

/** 샘플 계좌 */
export const SAMPLE_ACCOUNT: Account = {
  id: "sample-account-1",
  userId: "sample-user",
  balance: 100_000_000,
  initialCapital: 100_000_000,
  totalAsset: 100_000_000,
  totalProfit: 0,
  totalProfitRate: 0,
  createdAt: new Date().toISOString(),
};

/** 샘플 보유종목 */
export const SAMPLE_HOLDINGS: Holding[] = [
  {
    stockCode: "005930",
    stockName: "삼성전자",
    quantity: 100,
    avgPrice: 70000,
    currentPrice: 71500,
    totalValue: 7_150_000,
    profit: 150_000,
    profitRate: 2.14,
  },
  {
    stockCode: "035420",
    stockName: "NAVER",
    quantity: 10,
    avgPrice: 210000,
    currentPrice: 214500,
    totalValue: 2_145_000,
    profit: 45_000,
    profitRate: 2.14,
  },
];
