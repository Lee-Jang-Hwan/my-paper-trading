"use client";

import { useEffect, useRef } from "react";
import { useAgentStore } from "@/stores/agent-store";
import { type AgentType, AGENT_INFO } from "@/types/agent";

export default function LiveDebateViewer({
  conversationId,
}: {
  conversationId: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const liveConversations = useAgentStore((s) => s.liveConversations);
  const conv = liveConversations.get(conversationId);

  // 자동 스크롤
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [conv?.messages.length]);

  if (!conv) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-gray-700 bg-gray-900/80">
        <p className="text-sm text-gray-500">토론 대기 중...</p>
      </div>
    );
  }

  const isActive = conv.status === "active";
  const progress = conv.maxTurns
    ? Math.round((conv.messages.length / conv.maxTurns) * 100)
    : 0;

  return (
    <div className="flex flex-col rounded-xl border border-gray-700 bg-gray-900/80">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-700 px-4 py-3">
        <div className="flex items-center gap-2">
          {isActive && (
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-red-500" />
          )}
          <h3 className="text-sm font-bold text-white">
            {isActive ? "LIVE" : "완료"} - {conv.meetingType ? "회의" : "토론"}
          </h3>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">
            {conv.messages.length}{conv.maxTurns ? `/${conv.maxTurns}` : ""} 턴
          </span>
          {/* 참가자 목록 */}
          <div className="flex -space-x-1">
            {conv.participants.map((p) => {
              const info = AGENT_INFO[p.agent_type as AgentType];
              return (
                <span
                  key={p.agent_type}
                  className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs ${info?.bgColor ?? "bg-gray-600"}`}
                  title={p.name}
                >
                  {info?.emoji ?? "?"}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      {/* 주제 */}
      <div className="border-b border-gray-800 px-4 py-2">
        <p className="text-xs text-gray-400">
          주제: <span className="text-gray-200">{conv.topic}</span>
        </p>
      </div>

      {/* 진행률 */}
      {conv.maxTurns && (
        <div className="px-4 pt-2">
          <div className="h-1 w-full overflow-hidden rounded-full bg-gray-800">
            <div
              className="h-full rounded-full bg-blue-500 transition-all duration-500"
              style={{ width: `${Math.min(progress, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
        style={{ maxHeight: "400px", minHeight: "200px" }}
      >
        {conv.messages.map((msg, idx) => {
          const info = AGENT_INFO[msg.speaker_type as AgentType];
          const isLeft = idx % 2 === 0;

          return (
            <div
              key={idx}
              className={`flex gap-2 ${isLeft ? "" : "flex-row-reverse"}`}
            >
              {/* avatar */}
              <div
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm ${info?.bgColor ?? "bg-gray-600"}`}
              >
                {info?.emoji ?? "?"}
              </div>

              {/* bubble */}
              <div
                className={`max-w-[75%] rounded-xl px-3 py-2 ${
                  isLeft
                    ? "rounded-tl-sm bg-gray-800"
                    : "rounded-tr-sm bg-gray-700/70"
                }`}
              >
                <div className="mb-1 flex items-center gap-1.5">
                  <span
                    className={`text-xs font-semibold ${info?.color ?? "text-gray-400"}`}
                  >
                    {msg.speaker}
                  </span>
                  {msg.round !== undefined && (
                    <span className="text-[10px] text-gray-500">
                      R{msg.round}
                    </span>
                  )}
                </div>
                <p className="text-xs leading-relaxed text-gray-200">
                  {msg.content}
                </p>
              </div>
            </div>
          );
        })}

        {/* typing indicator */}
        {isActive && (
          <div className="flex items-center gap-2 pl-10">
            <div className="flex gap-1">
              <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-gray-500 [animation-delay:0ms]" />
              <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-gray-500 [animation-delay:150ms]" />
              <span className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-gray-500 [animation-delay:300ms]" />
            </div>
            <span className="text-[11px] text-gray-500">다음 발언 준비 중...</span>
          </div>
        )}
      </div>

      {/* 결론 */}
      {conv.conclusion && (
        <div className="border-t border-gray-700 px-4 py-3">
          <div className="rounded-lg border border-emerald-800/40 bg-emerald-950/20 px-3 py-2">
            <p className="mb-1 text-xs font-semibold text-emerald-400">결론</p>
            <p className="text-xs leading-relaxed text-gray-200">
              {conv.conclusion}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
