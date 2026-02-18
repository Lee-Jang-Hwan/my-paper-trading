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
    let disposed = false;

    async function initChart() {
      if (!chartContainerRef.current) return;

      const lc = await import("lightweight-charts");

      if (disposed || !chartContainerRef.current) return;

      const cs = getComputedStyle(document.documentElement);
      const bg = cs.getPropertyValue("--background").trim();
      const fg = cs.getPropertyValue("--foreground").trim();
      const border = cs.getPropertyValue("--border").trim();

      const chart = lc.createChart(chartContainerRef.current, {
        layout: {
          background: { type: lc.ColorType.Solid, color: bg || "#0a0a0f" },
          textColor: fg || "#f9fafb",
          fontSize: 12,
        },
        grid: {
          vertLines: { color: border || "#1f2937" },
          horzLines: { color: border || "#1f2937" },
        },
        crosshair: {
          mode: lc.CrosshairMode.Normal,
          vertLine: { labelBackgroundColor: bg || "#0a0a0f" },
          horzLine: { labelBackgroundColor: bg || "#0a0a0f" },
        },
        rightPriceScale: {
          borderColor: border || "#1f2937",
          scaleMargins: { top: 0.1, bottom: 0.3 },
        },
        timeScale: {
          borderColor: border || "#1f2937",
          timeVisible: true,
          secondsVisible: false,
        },
        width: chartContainerRef.current.clientWidth,
        height: chartContainerRef.current.clientHeight,
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

      // 초기 데이터 세팅
      const initCandles = candleData && candleData.length > 0 ? candleData : sampleCandles.current;
      const initVolumes = volumeData && volumeData.length > 0 ? volumeData : candlesToVolume(initCandles);

      candleSeries.setData(
        initCandles.map((c) => ({
          time: c.time as Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );
      volumeSeries.setData(
        initVolumes.map((v) => ({
          time: v.time as Time,
          value: v.value,
          color: v.color,
        }))
      );

      chart.timeScale().fitContent();

      // 리사이즈 핸들러
      const resizeObserver = new ResizeObserver((entries) => {
        if (entries[0] && chartRef.current) {
          const { width, height } = entries[0].contentRect;
          chartRef.current.applyOptions({ width, height });
        }
      });
      resizeObserver.observe(chartContainerRef.current);

      // 테마 변경 감지
      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      const handleThemeChange = () => {
        if (!chartRef.current) return;
        const updatedCs = getComputedStyle(document.documentElement);
        const newBg = updatedCs.getPropertyValue("--background").trim();
        const newFg = updatedCs.getPropertyValue("--foreground").trim();
        const newBorder = updatedCs.getPropertyValue("--border").trim();

        chartRef.current.applyOptions({
          layout: {
            background: { type: lc.ColorType.Solid, color: newBg || "#0a0a0f" },
            textColor: newFg || "#f9fafb",
          },
          grid: {
            vertLines: { color: newBorder || "#1f2937" },
            horzLines: { color: newBorder || "#1f2937" },
          },
        });
      };
      mediaQuery.addEventListener("change", handleThemeChange);

      return () => {
        disposed = true;
        mediaQuery.removeEventListener("change", handleThemeChange);
        resizeObserver.disconnect();
        chart.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
        volumeSeriesRef.current = null;
      };
    }

    let cleanup: (() => void) | undefined;
    initChart().then((fn) => {
      cleanup = fn;
    });

    return () => {
      cleanup?.();
    };
    // 마운트 시 1회만 실행
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 데이터 업데이트 (차트 재생성 없이 시리즈만 갱신)
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

    const candles = candleData && candleData.length > 0 ? candleData : sampleCandles.current;
    const volumes = volumeData && volumeData.length > 0 ? volumeData : candlesToVolume(candles);

    candleSeriesRef.current.setData(
      candles.map((c) => ({
        time: c.time as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );
    volumeSeriesRef.current.setData(
      volumes.map((v) => ({
        time: v.time as Time,
        value: v.value,
        color: v.color,
      }))
    );
  }, [candleData, volumeData]);

  return (
    <div className="flex h-full flex-col">
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

      {/* 차트 영역 */}
      <div ref={chartContainerRef} className="min-h-0 flex-1" />
    </div>
  );
}
