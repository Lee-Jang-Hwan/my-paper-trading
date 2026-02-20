"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import type { CandleData, VolumeData, Timeframe } from "@/types/trading";
import { TIMEFRAME_LABELS } from "@/types/trading";
import {
  generateSampleCandles,
  candlesToVolume,
} from "@/lib/sample-data";

// ============================================================
// StockChart – lightweight-charts v5 (TradingView)
// ============================================================

/** time 문자열을 lightweight-charts Time 타입으로 변환 */
function parseChartTime(t: string): Time {
  // epoch seconds (숫자만으로 이루어진 10자리 이상 문자열) → number
  if (/^\d{10,}$/.test(t)) {
    return Number(t) as unknown as Time;
  }
  // "YYYY-MM-DD" 형식 → 그대로 string
  return t as Time;
}

interface StockChartProps {
  candleData?: CandleData[];
  volumeData?: VolumeData[];
  timeframe?: Timeframe;
  onTimeframeChange?: (tf: Timeframe) => void;
}

export default function StockChart({
  candleData,
  volumeData,
  timeframe = "1d",
  onTimeframeChange,
}: StockChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const [selectedTf, setSelectedTf] = useState<Timeframe>(timeframe);
  const [chartReady, setChartReady] = useState(false);
  const [chartError, setChartError] = useState<string>("");

  // 외부에서 timeframe prop이 변경되면 내부 상태 동기화
  useEffect(() => {
    setSelectedTf(timeframe);
  }, [timeframe]);

  // 샘플 데이터 fallback (한 번만 생성)
  const sampleCandles = useRef(generateSampleCandles());

  const handleTimeframeChange = useCallback(
    (tf: Timeframe) => {
      setSelectedTf(tf);
      onTimeframeChange?.(tf);
    },
    [onTimeframeChange]
  );

  // 차트 생성 (마운트 시 1회)
  useEffect(() => {
    // disposed를 즉시 접근 가능한 곳에 둠 — StrictMode cleanup에서도 설정 가능
    let disposed = false;
    let resizeOb: ResizeObserver | null = null;
    let mediaQry: MediaQueryList | null = null;
    let themeHandler: (() => void) | null = null;

    async function initChart() {
      const container = chartContainerRef.current;
      if (!container) return;

      // 컨테이너 크기 확인 — 0이면 렌더 완료 대기
      let { clientWidth: w, clientHeight: h } = container;
      if (w === 0 || h === 0) {
        await new Promise<void>((resolve) => {
          const ro = new ResizeObserver(() => {
            if (container.clientWidth > 0 && container.clientHeight > 0) {
              ro.disconnect();
              resolve();
            }
          });
          ro.observe(container);
          setTimeout(() => { ro.disconnect(); resolve(); }, 2000);
        });
        w = container.clientWidth;
        h = container.clientHeight;
      }
      if (w === 0) w = 600;
      if (h === 0) h = 300;

      // async 경계 후 항상 disposed 체크
      if (disposed) return;

      const lc = await import("lightweight-charts");

      if (disposed || !chartContainerRef.current) return;

      if (!lc.CandlestickSeries || !lc.HistogramSeries) {
        console.error("[StockChart] exports missing:", Object.keys(lc));
        setChartError("차트 라이브러리 로드 실패");
        return;
      }

      // 이전 차트가 남아있으면 제거 (StrictMode 대응)
      if (chartRef.current) {
        try { chartRef.current.remove(); } catch { /* ignore */ }
        chartRef.current = null;
      }

      const cs = getComputedStyle(document.documentElement);
      const bg = cs.getPropertyValue("--background").trim() || "#0a0a0f";
      const fg = cs.getPropertyValue("--foreground").trim() || "#f9fafb";
      const border = cs.getPropertyValue("--border").trim() || "#1f2937";

      const chart = lc.createChart(chartContainerRef.current, {
        layout: {
          background: { type: lc.ColorType.Solid, color: bg },
          textColor: fg,
          fontSize: 12,
        },
        grid: {
          vertLines: { color: border },
          horzLines: { color: border },
        },
        crosshair: {
          mode: lc.CrosshairMode.Normal,
          vertLine: { labelBackgroundColor: bg },
          horzLine: { labelBackgroundColor: bg },
        },
        rightPriceScale: {
          borderColor: border,
          scaleMargins: { top: 0.1, bottom: 0.3 },
        },
        timeScale: {
          borderColor: border,
          timeVisible: true,
          secondsVisible: false,
        },
        width: w,
        height: h,
      });

      chartRef.current = chart;

      // 캔들스틱 시리즈
      const candleSeries = chart.addSeries(lc.CandlestickSeries, {
        upColor: "#ef4444",
        downColor: "#3b82f6",
        borderUpColor: "#ef4444",
        borderDownColor: "#3b82f6",
        wickUpColor: "#ef4444",
        wickDownColor: "#3b82f6",
      });
      candleSeriesRef.current = candleSeries;

      // 볼륨 히스토그램
      const volumeSeries = chart.addSeries(lc.HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeriesRef.current = volumeSeries;

      // 리사이즈 핸들러
      resizeOb = new ResizeObserver((entries) => {
        if (entries[0] && chartRef.current) {
          const { width, height } = entries[0].contentRect;
          if (width > 0 && height > 0) {
            chartRef.current.applyOptions({ width, height });
          }
        }
      });
      resizeOb.observe(chartContainerRef.current);

      // 테마 변경 감지
      mediaQry = window.matchMedia("(prefers-color-scheme: dark)");
      themeHandler = () => {
        if (!chartRef.current) return;
        const updatedCs = getComputedStyle(document.documentElement);
        const newBg = updatedCs.getPropertyValue("--background").trim() || "#0a0a0f";
        const newFg = updatedCs.getPropertyValue("--foreground").trim() || "#f9fafb";
        const newBorder = updatedCs.getPropertyValue("--border").trim() || "#1f2937";
        chartRef.current.applyOptions({
          layout: {
            background: { type: lc.ColorType.Solid, color: newBg },
            textColor: newFg,
          },
          grid: {
            vertLines: { color: newBorder },
            horzLines: { color: newBorder },
          },
        });
      };
      mediaQry.addEventListener("change", themeHandler);

      console.log("[StockChart] Chart initialized successfully");
      setChartReady(true);
      setChartError("");
    }

    initChart().catch((err) => {
      console.error("[StockChart] Chart initialization failed:", err);
      setChartError(`차트 초기화 실패: ${err?.message || err}`);
    });

    return () => {
      // StrictMode에서 async initChart가 진행 중일 때도 즉시 취소
      disposed = true;
      setChartReady(false);

      // 리소스 정리
      if (themeHandler && mediaQry) {
        mediaQry.removeEventListener("change", themeHandler);
      }
      resizeOb?.disconnect();

      if (chartRef.current) {
        try { chartRef.current.remove(); } catch { /* ignore */ }
        chartRef.current = null;
      }
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 데이터 업데이트 — chartReady가 true일 때만 실행
  useEffect(() => {
    if (!chartReady || !candleSeriesRef.current || !volumeSeriesRef.current) return;

    const candles = candleData && candleData.length > 0 ? candleData : sampleCandles.current;
    const vols = volumeData && volumeData.length > 0 ? volumeData : candlesToVolume(candles);

    console.log(`[StockChart] Setting data: ${candles.length} candles`);

    try {
      candleSeriesRef.current.setData(
        candles.map((c) => ({
          time: parseChartTime(c.time),
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );
      volumeSeriesRef.current.setData(
        vols.map((v) => ({
          time: parseChartTime(v.time),
          value: v.value,
          color: v.color,
        }))
      );

      chartRef.current?.timeScale().fitContent();
    } catch (err) {
      console.error("[StockChart] Error setting chart data:", err);
    }
  }, [chartReady, candleData, volumeData]);

  return (
    <div className="flex h-full flex-col" style={{ minHeight: 200 }}>
      {/* 타임프레임 선택 */}
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        {(Object.keys(TIMEFRAME_LABELS) as Timeframe[]).map((tf) => (
          <button
            key={tf}
            onClick={() => handleTimeframeChange(tf)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              selectedTf === tf
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {TIMEFRAME_LABELS[tf]}
          </button>
        ))}
      </div>

      {/* 차트 영역 — chartContainerRef는 lightweight-charts 전용 (React 자식 없음) */}
      <div className="relative min-h-0 flex-1" style={{ minHeight: 160 }}>
        <div ref={chartContainerRef} className="absolute inset-0" />
        {chartError && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-card/90">
            <p className="text-sm text-red-400">{chartError}</p>
          </div>
        )}
      </div>
    </div>
  );
}
