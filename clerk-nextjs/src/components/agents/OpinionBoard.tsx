"use client";

import { useState, useCallback } from "react";
import { getAgentOpinions } from "@/services/api";
import { useAgentStore } from "@/stores/agent-store";
import { type AgentType, AGENT_INFO } from "@/types/agent";

const SENTIMENT_CONFIG = {
  bullish: { label: "매수", color: "text-red-400", bg: "bg-red-500/20", border: "border-red-800/40" },
  bearish: { label: "매도", color: "text-blue-400", bg: "bg-blue-500/20", border: "border-blue-800/40" },
  neutral: { label: "중립", color: "text-gray-400", bg: "bg-gray-500/20", border: "border-gray-600/40" },
} as const;

const AGREEMENT_CONFIG = {
  strong: { label: "강한 합의", color: "bg-emerald-500", width: "100%" },
  moderate: { label: "다수 동의", color: "bg-blue-500", width: "75%" },
  mixed: { label: "의견 혼재", color: "bg-yellow-500", width: "50%" },
  divided: { label: "의견 대립", color: "bg-red-500", width: "25%" },
} as const;

interface OpinionBoardProps {
  token: string | null;
}

export default function OpinionBoard({ token }: OpinionBoardProps) {
  const [topic, setTopic] = useState("");
  const [stockCode, setStockCode] = useState("");

  const opinionSummary = useAgentStore((s) => s.opinionSummary);
  const opinionLoading = useAgentStore((s) => s.opinionLoading);
  const setOpinionSummary = useAgentStore((s) => s.setOpinionSummary);
  const setOpinionLoading = useAgentStore((s) => s.setOpinionLoading);

  const handleSubmit = useCallback(async () => {
    if (!topic.trim() || opinionLoading) return;
    setOpinionLoading(true);
    setOpinionSummary(null);

    try {
      const result = await getAgentOpinions(
        token,
        topic.trim(),
        stockCode.trim() || undefined
      );
      setOpinionSummary(result);
    } catch {
      // 에러 시 무시
    } finally {
      setOpinionLoading(false);
    }
  }, [topic, stockCode, token, opinionLoading, setOpinionSummary, setOpinionLoading]);

  const agreement = opinionSummary
    ? AGREEMENT_CONFIG[opinionSummary.agreement_level]
    : null;

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-900/80 p-4">
      <h3 className="mb-3 text-sm font-bold text-white">에이전트 의견 종합</h3>

      {/* 입력 영역 */}
      <div className="mb-4 flex gap-2">
        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="주제를 입력하세요 (예: KOSPI 하반기 전망)"
          disabled={opinionLoading}
          className="flex-1 rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none disabled:opacity-50"
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSubmit();
          }}
        />
        <input
          type="text"
          value={stockCode}
          onChange={(e) => setStockCode(e.target.value)}
          placeholder="종목코드"
          disabled={opinionLoading}
          className="w-28 rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={handleSubmit}
          disabled={!topic.trim() || opinionLoading}
          className="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {opinionLoading ? "분석 중..." : "조회"}
        </button>
      </div>

      {/* 로딩 스켈레톤 */}
      {opinionLoading && (
        <div className="space-y-3">
          <div className="h-3 w-3/4 animate-pulse rounded bg-gray-700" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-40 animate-pulse rounded-xl border border-gray-700 bg-gray-800/50"
              />
            ))}
          </div>
        </div>
      )}

      {/* 결과 */}
      {opinionSummary && !opinionLoading && (
        <div className="space-y-4">
          {/* 합의도 */}
          {agreement && (
            <div className="rounded-lg border border-gray-700 bg-gray-800/50 px-4 py-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-gray-400">합의도</span>
                <span className="text-xs font-semibold text-white">
                  {agreement.label}
                </span>
              </div>
              <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-gray-700">
                <div
                  className={`h-full rounded-full ${agreement.color} transition-all duration-700`}
                  style={{ width: agreement.width }}
                />
              </div>
              <p className="text-xs leading-relaxed text-gray-300">
                {opinionSummary.consensus}
              </p>
            </div>
          )}

          {/* 2x2 에이전트 의견 카드 */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {opinionSummary.opinions.map((opinion) => {
              const agentInfo = AGENT_INFO[opinion.agent_type as AgentType];
              const sentiment = SENTIMENT_CONFIG[opinion.sentiment] ?? SENTIMENT_CONFIG.neutral;
              const confidencePercent = Math.round(opinion.confidence * 100);

              return (
                <div
                  key={opinion.agent_type}
                  className={`rounded-xl border ${sentiment.border} bg-gray-800/60 p-3`}
                >
                  {/* 에이전트 헤더 */}
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-sm ${agentInfo?.bgColor ?? "bg-gray-600"}`}
                      >
                        {agentInfo?.emoji ?? "?"}
                      </span>
                      <div>
                        <p className={`text-xs font-semibold ${agentInfo?.color ?? "text-gray-400"}`}>
                          {opinion.agent_name}
                        </p>
                        <p className="text-[10px] text-gray-500">
                          {agentInfo?.role ?? ""}
                        </p>
                      </div>
                    </div>
                    {/* 감성 배지 */}
                    <span
                      className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${sentiment.color} ${sentiment.bg}`}
                    >
                      {sentiment.label}
                    </span>
                  </div>

                  {/* 의견 */}
                  <p className="mb-2 text-xs leading-relaxed text-gray-200">
                    {opinion.opinion}
                  </p>

                  {/* 신뢰도 */}
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-[10px] text-gray-500">신뢰도</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-700">
                      <div
                        className="h-full rounded-full bg-blue-500 transition-all duration-500"
                        style={{ width: `${confidencePercent}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-medium text-gray-400">
                      {confidencePercent}%
                    </span>
                  </div>

                  {/* 핵심 포인트 */}
                  {opinion.key_points.length > 0 && (
                    <ul className="space-y-0.5">
                      {opinion.key_points.map((point, idx) => (
                        <li
                          key={idx}
                          className="flex items-start gap-1 text-[11px] text-gray-400"
                        >
                          <span className="mt-0.5 shrink-0 text-gray-600">-</span>
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
