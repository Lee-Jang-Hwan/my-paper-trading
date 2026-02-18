"use client";

import { useState } from "react";

interface Segment {
  label: string;
  value: number;
  color: string;
}

interface DonutChartProps {
  data: Segment[];
  totalLabel: string;
  totalValue: string;
}

export function DonutChart({ data, totalLabel, totalValue }: DonutChartProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return null;

  // SVG donut via stroke-dasharray
  const size = 160;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 58;
  const circumference = 2 * Math.PI * radius;

  let accumulated = 0;
  const arcs = data.map((seg, i) => {
    const pct = seg.value / total;
    const dashLen = pct * circumference;
    const dashGap = circumference - dashLen;
    const offset = -(accumulated * circumference) + circumference * 0.25; // start from top
    accumulated += pct;
    return { ...seg, pct, dashLen, dashGap, offset, idx: i };
  });

  const hovered = hoveredIdx !== null ? data[hoveredIdx] : null;
  const hoveredPct = hovered ? ((hovered.value / total) * 100).toFixed(1) : null;

  return (
    <div className="flex flex-col items-center gap-3">
      {/* SVG */}
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="shrink-0"
      >
        {arcs.map((arc) => (
          <circle
            key={arc.idx}
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke={arc.color}
            strokeWidth={hoveredIdx === arc.idx ? 22 : 18}
            strokeDasharray={`${arc.dashLen} ${arc.dashGap}`}
            strokeDashoffset={arc.offset}
            className="transition-all duration-200"
            style={{ cursor: "pointer" }}
            onMouseEnter={() => setHoveredIdx(arc.idx)}
            onMouseLeave={() => setHoveredIdx(null)}
          />
        ))}
        {/* Center text */}
        <text
          x={cx}
          y={cy - 6}
          textAnchor="middle"
          className="fill-muted-foreground text-[10px]"
        >
          {hovered ? hovered.label : totalLabel}
        </text>
        <text
          x={cx}
          y={cy + 10}
          textAnchor="middle"
          className="fill-foreground text-[11px] font-semibold"
        >
          {hovered
            ? `${hoveredPct}%`
            : totalValue}
        </text>
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap justify-center gap-x-3 gap-y-1">
        {data.map((seg, i) => (
          <div
            key={i}
            className="flex items-center gap-1 text-[10px]"
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
          >
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: seg.color }}
            />
            <span className={hoveredIdx === i ? "text-foreground font-medium" : "text-muted-foreground"}>
              {seg.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
