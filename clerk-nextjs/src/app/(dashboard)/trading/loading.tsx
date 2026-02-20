export default function TradingLoading() {
  return (
    <div className="flex h-[calc(100vh-4.5rem)] gap-2">
      {/* 종목 리스트 */}
      <div className="hidden w-72 animate-pulse rounded-lg border border-border bg-card lg:block" />
      {/* 차트 + 호가 */}
      <div className="flex flex-1 flex-col gap-2">
        <div className="flex-[6] animate-pulse rounded-lg border border-border bg-card" />
        <div className="flex-[4] animate-pulse rounded-lg border border-border bg-card" />
      </div>
      {/* 주문 패널 */}
      <div className="hidden w-80 animate-pulse rounded-lg border border-border bg-card lg:block" />
    </div>
  );
}
