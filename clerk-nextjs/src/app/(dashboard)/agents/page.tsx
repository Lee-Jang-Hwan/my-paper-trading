"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { useAgentWebSocket } from "@/hooks/useAgentWebSocket";
import { useAgentStore } from "@/stores/agent-store";
import { setApiTokenRefresher } from "@/services/api";
import AgentWorld from "@/components/agents/AgentWorld";
import DebatePanel from "@/components/agents/DebatePanel";
import OpinionBoard from "@/components/agents/OpinionBoard";

export default function AgentsPage() {
  const { getToken } = useAuth();
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const [token, setToken] = useState<string | null>(null);

  // WebSocket 연결
  useAgentWebSocket();

  // 토큰 관리 — Clerk JWT는 ~60초 만료, 50초마다 갱신
  useEffect(() => {
    setApiTokenRefresher(getToken);
    getToken().then(setToken);
    const id = setInterval(() => {
      getToken().then(setToken);
    }, 50_000);
    return () => clearInterval(id);
  }, [getToken]);

  return (
    <div className="space-y-6">
      {/* 페이지 헤더 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">AI 에이전트</h1>
          <p className="text-sm text-gray-400">
            AI 에이전트들의 실시간 토론을 시청하고, 의견을 조회하세요.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              wsConnected ? "bg-green-400" : "bg-gray-600"
            }`}
          />
          <span className="text-xs text-gray-500">
            {wsConnected ? "실시간 연결" : "연결 중..."}
          </span>
        </div>
      </div>

      {/* 2열 레이아웃 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 좌측: 에이전트 월드 */}
        <div className="space-y-4">
          <AgentWorld token={token} />
        </div>

        {/* 우측: 토론 패널 */}
        <div className="space-y-4">
          <DebatePanel token={token} />
        </div>
      </div>

      {/* 하단: 의견 보드 (전체 폭) */}
      <OpinionBoard token={token} />
    </div>
  );
}
