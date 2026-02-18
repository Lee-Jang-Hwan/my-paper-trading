// ============================================================
// Number / price formatting utilities (Korean locale)
// ============================================================

/** 숫자를 한국식 쉼표 포맷으로 변환 */
export function formatNumber(n: number | undefined | null): string {
  if (n == null) return "---";
  return n.toLocaleString("ko-KR");
}

/** 가격 포맷 (원 단위) */
export function formatPrice(price: number | undefined | null): string {
  if (price == null) return "---";
  return price.toLocaleString("ko-KR");
}

/** 퍼센트 포맷 (+/-) */
export function formatPercent(rate: number | undefined | null): string {
  if (rate == null) return "---";
  const sign = rate > 0 ? "+" : "";
  return `${sign}${rate.toFixed(2)}%`;
}

/** 변동 금액 포맷 (+/-) */
export function formatChange(change: number | undefined | null): string {
  if (change == null) return "---";
  const sign = change > 0 ? "+" : "";
  return `${sign}${change.toLocaleString("ko-KR")}`;
}

/** 변동 방향에 따른 CSS 색상 클래스 */
export function priceColorClass(change: number | undefined | null): string {
  if (change == null || change === 0) return "text-muted-foreground";
  return change > 0 ? "text-red-500" : "text-blue-500";
}

/** 변동 방향에 따른 배경 색상 클래스 */
export function priceBgClass(change: number | undefined | null): string {
  if (change == null || change === 0) return "";
  return change > 0 ? "bg-red-500/10" : "bg-blue-500/10";
}

// ============================================================
// 호가 단위 (Tick Size) – 한국 거래소 규칙
// ============================================================

/** 가격에 따른 호가 단위 반환 (KRX 규칙) */
export function getTickSize(price: number): number {
  if (price < 2_000) return 1;
  if (price < 5_000) return 5;
  if (price < 20_000) return 10;
  if (price < 50_000) return 50;
  if (price < 200_000) return 100;
  if (price < 500_000) return 500;
  return 1_000;
}

/** 가격을 호가 단위에 맞게 올림 */
export function roundToTickUp(price: number): number {
  const tick = getTickSize(price);
  return Math.ceil(price / tick) * tick;
}

/** 가격을 호가 단위에 맞게 내림 */
export function roundToTickDown(price: number): number {
  const tick = getTickSize(price);
  return Math.floor(price / tick) * tick;
}

/** 가격에서 한 틱 올리기 */
export function tickUp(price: number): number {
  const tick = getTickSize(price);
  return price + tick;
}

/** 가격에서 한 틱 내리기 */
export function tickDown(price: number): number {
  const tick = getTickSize(price);
  return Math.max(tick, price - tick);
}
