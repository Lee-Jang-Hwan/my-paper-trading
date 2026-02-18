"use client";

import { useState, useCallback, useEffect } from "react";
import { startAgentDebate } from "@/services/api";
import { useAgentStore } from "@/stores/agent-store";
import LiveDebateViewer from "./LiveDebateViewer";

interface DebatePanelProps {
  token: string | null;
}

export default function DebatePanel({ token }: DebatePanelProps) {
  const [topic, setTopic] = useState("");
  const [stockCode, setStockCode] = useState("");
  const [stockName, setStockName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  const activeDebateId = useAgentStore((s) => s.activeDebateId);
  const setActiveDebateId = useAgentStore((s) => s.setActiveDebateId);
  const liveConversations = useAgentStore((s) => s.liveConversations);

  // 가장 최근 활성 대화 찾기 (activeDebateId가 없을 때)
  const latestConvId =
    activeDebateId ??
    Array.from(liveConversations.entries())
      .filter(([, c]) => c.status === "active")
      .pop()?.[0] ??
    Array.from(liveConversations.entries()).pop()?.[0] ??
    null;

  // 쿨다운 타이머
  useEffect(() => {
    if (cooldown <= 0) return;
    const id = setInterval(() => {
      setCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [cooldown]);

  const handleSubmit = useCallback(async () => {
    if (!topic.trim() || loading || cooldown > 0) return;
    setLoading(true);
    setError(null);

    try {
      const res = await startAgentDebate(
        token,
        topic.trim(),
        stockCode.trim() || undefined,
        stockName.trim() || undefined
      );

      if (res.status === "started" && res.conversation_id) {
        setActiveDebateId(res.conversation_id);
        setTopic("");
        setStockCode("");
        setStockName("");
        setCooldown(60);
      } else {
        setError(res.message ?? "토론을 시작할 수 없습니다.");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "토론 시작 실패";
      setError(msg);
      // 429 쿨다운 처리
      if (msg.includes("429")) {
        setCooldown(60);
      }
    } finally {
      setLoading(false);
    }
  }, [topic, stockCode, stockName, token, loading, cooldown, setActiveDebateId]);

  const isDebateActive = !!activeDebateId;

  return (
    <div className="space-y-4">
      {/* 입력 폼 */}
      <div className="rounded-xl border border-gray-700 bg-gray-900/80 p-4">
        <h3 className="mb-3 text-sm font-bold text-white">토론 시작하기</h3>

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs text-gray-400">토론 주제</label>
            <input
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="예: 삼성전자 현재 매수 적기인가?"
              disabled={isDebateActive || loading}
              className="w-full rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none disabled:opacity-50"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSubmit();
              }}
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-xs text-gray-400">
                종목코드 (선택)
              </label>
              <input
                type="text"
                value={stockCode}
                onChange={(e) => setStockCode(e.target.value)}
                placeholder="005930"
                disabled={isDebateActive || loading}
                className="w-full rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none disabled:opacity-50"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">
                종목명 (선택)
              </label>
              <input
                type="text"
                value={stockName}
                onChange={(e) => setStockName(e.target.value)}
                placeholder="삼성전자"
                disabled={isDebateActive || loading}
                className="w-full rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none disabled:opacity-50"
              />
            </div>
          </div>

          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}

          <button
            onClick={handleSubmit}
            disabled={!topic.trim() || isDebateActive || loading || cooldown > 0}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? (
              <>
                <svg
                  className="h-4 w-4 animate-spin"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                  />
                </svg>
                <span>시작 중...</span>
              </>
            ) : cooldown > 0 ? (
              <span>재시작 가능: {cooldown}초</span>
            ) : isDebateActive ? (
              <span>토론 진행 중...</span>
            ) : (
              <span>토론 시작</span>
            )}
          </button>
        </div>
      </div>

      {/* 실시간 토론 뷰어 */}
      {latestConvId && <LiveDebateViewer conversationId={latestConvId} />}
    </div>
  );
}
