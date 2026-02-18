"use client";

import { useState, useEffect, useCallback } from "react";
import { getAgentWorldState, triggerAgentMeeting } from "@/services/api";
import { useAgentStore } from "@/stores/agent-store";
import {
  type AgentType,
  type AgentState,
  type WorldState,
  type AgentConversation,
  AGENT_INFO,
  LOCATION_LABELS,
  ACTION_LABELS,
} from "@/types/agent";
import AskAgentPanel from "./AskAgentPanel";

// ---- constants ----

const POLL_INTERVAL_MS = 15_000; // 15초 (WS 폴백용)

/** Ordered list of location keys for the 2x3 grid */
const GRID_LOCATIONS = [
  "market_board",
  "analysis_desk",
  "news_terminal",
  "portfolio_board",
  "meeting_table",
  "user_desk",
] as const;

/** Background tint per location for visual distinction */
const LOCATION_STYLE: Record<string, string> = {
  market_board: "border-blue-800/40 bg-blue-950/20",
  analysis_desk: "border-emerald-800/40 bg-emerald-950/20",
  news_terminal: "border-yellow-800/40 bg-yellow-950/20",
  portfolio_board: "border-purple-800/40 bg-purple-950/20",
  meeting_table: "border-orange-800/40 bg-orange-950/20",
  user_desk: "border-gray-700 bg-gray-800/40",
};

// ---- helper ----

function agentsByLocation(agents: AgentState[]): Record<string, AgentState[]> {
  const map: Record<string, AgentState[]> = {};
  for (const a of agents) {
    if (!map[a.location]) map[a.location] = [];
    map[a.location].push(a);
  }
  return map;
}

function findConversationAtLocation(
  conversations: AgentConversation[],
  agents: AgentState[]
): AgentConversation | null {
  // Return the first conversation whose participants are currently talking
  const talkingNames = new Set(
    agents.filter((a) => a.is_in_conversation).map((a) => a.name)
  );
  if (talkingNames.size === 0) return null;
  return (
    conversations.find((c) => {
      if (c.participants) {
        return c.participants.some((p) => talkingNames.has(p));
      }
      return (
        (c.initiator && talkingNames.has(c.initiator)) ||
        (c.target && talkingNames.has(c.target))
      );
    }) ?? null
  );
}

// ---- sub-components ----

function AgentBadge({ agent }: { agent: AgentState }) {
  const info = AGENT_INFO[agent.agent_type as AgentType] ?? {
    emoji: "?",
    color: "text-gray-400",
    bgColor: "bg-gray-500/20",
    name: agent.name,
  };
  const action = ACTION_LABELS[agent.action] ?? {
    label: agent.action,
    icon: "",
  };

  return (
    <div
      className={`flex items-center gap-1.5 rounded-md px-2 py-1 ${info.bgColor}`}
    >
      <span className="text-base leading-none">{info.emoji}</span>
      <span className={`text-xs font-semibold ${info.color}`}>
        {agent.name}
      </span>
      <span className="text-[11px] leading-none" title={action.label}>
        {action.icon}
      </span>
      {agent.is_in_conversation && (
        <span className="ml-0.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-green-400" />
      )}
    </div>
  );
}

function LocationCell({
  locationKey,
  agents,
  activeConversation,
}: {
  locationKey: string;
  agents: AgentState[];
  activeConversation: AgentConversation | null;
}) {
  const label = LOCATION_LABELS[locationKey] ?? locationKey;
  const style = LOCATION_STYLE[locationKey] ?? "border-gray-700 bg-gray-800/40";

  return (
    <div
      className={`relative flex min-h-[120px] flex-col gap-2 rounded-xl border p-3 transition-colors ${style}`}
    >
      {/* location header */}
      <span className="text-[11px] font-medium uppercase tracking-wide text-gray-500">
        {label}
      </span>

      {/* agents */}
      {agents.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {agents.map((a) => (
            <AgentBadge key={a.agent_type} agent={a} />
          ))}
        </div>
      ) : (
        <span className="text-[11px] italic text-gray-600">비어 있음</span>
      )}

      {/* action descriptions */}
      {agents.length > 0 && (
        <div className="mt-auto space-y-0.5">
          {agents.map((a) => (
            <p
              key={a.agent_type}
              className="truncate text-[11px] text-gray-400"
              title={a.action_description}
            >
              {a.action_description}
            </p>
          ))}
        </div>
      )}

      {/* live conversation bubble */}
      {activeConversation && (
        <div className="absolute -top-2 right-2 max-w-[180px] animate-pulse rounded-lg border border-gray-600 bg-gray-800 px-2.5 py-1.5 shadow-lg">
          <p className="truncate text-[11px] font-medium text-gray-200">
            {activeConversation.topic}
          </p>
        </div>
      )}
    </div>
  );
}

function ConversationLog({
  conversations,
}: {
  conversations: AgentConversation[];
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  if (conversations.length === 0) {
    return (
      <p className="py-4 text-center text-xs text-gray-500">
        아직 대화 기록이 없습니다.
      </p>
    );
  }

  const displayed = conversations.slice(0, 5);

  return (
    <div className="space-y-2">
      {displayed.map((conv, idx) => {
        const isExpanded = expandedIdx === idx;
        const isMeeting = !!conv.meeting_type;
        const title = isMeeting
          ? `[회의] ${conv.topic}`
          : `${conv.initiator ?? "?"} <> ${conv.target ?? "?"} : ${conv.topic}`;

        return (
          <div
            key={idx}
            className="rounded-lg border border-gray-700 bg-gray-800/60"
          >
            {/* header - click to toggle */}
            <button
              onClick={() => setExpandedIdx(isExpanded ? null : idx)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-gray-800"
            >
              <span className="text-xs">{isMeeting ? "\uD83D\uDCCB" : "\uD83D\uDCAC"}</span>
              <span className="flex-1 truncate text-xs font-medium text-gray-200">
                {title}
              </span>
              <span className="text-[11px] text-gray-500">
                {conv.messages.length}턴
              </span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`text-gray-500 transition-transform ${
                  isExpanded ? "rotate-180" : ""
                }`}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {/* expanded messages */}
            {isExpanded && (
              <div className="space-y-1 border-t border-gray-700 px-3 py-2">
                {conv.messages.map((msg, mi) => {
                  const speakerInfo =
                    AGENT_INFO[msg.speaker_type as AgentType] ?? null;
                  return (
                    <div key={mi} className="flex gap-2 text-xs">
                      <span
                        className={`shrink-0 font-semibold ${
                          speakerInfo?.color ?? "text-gray-400"
                        }`}
                      >
                        {speakerInfo?.emoji ?? ""} {msg.speaker}:
                      </span>
                      <span className="text-gray-300">{msg.content}</span>
                    </div>
                  );
                })}

                {conv.conclusion && (
                  <div className="mt-1 rounded-md bg-gray-700/40 px-2 py-1 text-[11px] text-gray-400">
                    결론: {conv.conclusion}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---- main component ----

interface AgentWorldProps {
  token: string | null;
}

export default function AgentWorld({ token }: AgentWorldProps) {
  const [world, setWorld] = useState<WorldState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAskPanel, setShowAskPanel] = useState(false);
  const [meetingLoading, setMeetingLoading] = useState(false);

  const setWorldState = useAgentStore((s) => s.setWorldState);
  const liveConversations = useAgentStore((s) => s.liveConversations);
  const activeCount = Array.from(liveConversations.values()).filter(
    (c) => c.status === "active"
  ).length;

  // ---- polling ----

  const fetchWorld = useCallback(async () => {
    try {
      const data = await getAgentWorldState(token);
      setWorld(data);
      setWorldState(data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "월드 상태를 불러올 수 없습니다."
      );
    } finally {
      setLoading(false);
    }
  }, [token, setWorldState]);

  useEffect(() => {
    fetchWorld();
    const id = setInterval(fetchWorld, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchWorld]);

  // ---- emergency meeting ----

  const handleMeeting = useCallback(async () => {
    setMeetingLoading(true);
    try {
      await triggerAgentMeeting(token);
      // refresh immediately
      await fetchWorld();
    } catch {
      // silently ignore – next poll will update
    } finally {
      setMeetingLoading(false);
    }
  }, [token, fetchWorld]);

  // ---- render helpers ----

  if (loading && !world) {
    return (
      <div className="flex min-h-[300px] items-center justify-center rounded-xl border border-gray-700 bg-gray-900">
        <div className="flex items-center gap-2 text-sm text-gray-400">
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
          <span>에이전트 월드 로딩 중...</span>
        </div>
      </div>
    );
  }

  if (error && !world) {
    return (
      <div className="flex min-h-[200px] flex-col items-center justify-center gap-3 rounded-xl border border-red-800/50 bg-gray-900 p-6">
        <p className="text-sm text-red-400">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            fetchWorld();
          }}
          className="rounded-md bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition-colors hover:bg-gray-700"
        >
          다시 시도
        </button>
      </div>
    );
  }

  const agents = world?.agents ?? [];
  const conversations = world?.recent_conversations ?? [];
  const locMap = agentsByLocation(agents);

  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-700 bg-gray-900 px-4 py-3">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-bold text-white">
            AI 에이전트 월드
          </h2>
          {activeCount > 0 && (
            <span className="flex items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 text-[11px] font-medium text-red-400">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-red-400" />
              LIVE {activeCount}
            </span>
          )}

          {world && (
            <div className="flex items-center gap-2 text-[11px] text-gray-500">
              <span>
                Tick #{world.tick_count}
              </span>
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  world.running ? "bg-green-400" : "bg-gray-600"
                }`}
              />
              <span>{world.running ? "실행 중" : "정지"}</span>
              {world.gemini_status && (
                <span className="text-gray-600">
                  | Gemini {world.gemini_status.available ? "ON" : "OFF"} (
                  {world.gemini_status.tokens_used.toLocaleString()} tokens)
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleMeeting}
            disabled={meetingLoading}
            className="flex h-8 items-center gap-1.5 rounded-lg border border-orange-700/50 bg-orange-900/20 px-3 text-xs font-medium text-orange-300 transition-colors hover:bg-orange-900/40 disabled:opacity-40"
          >
            {meetingLoading ? (
              <svg
                className="h-3.5 w-3.5 animate-spin"
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
            ) : (
              <span>&#x1F6A8;</span>
            )}
            <span>긴급 회의</span>
          </button>

          <button
            onClick={() => setShowAskPanel((v) => !v)}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-blue-600 px-3 text-xs font-medium text-white transition-colors hover:bg-blue-500"
          >
            <span>&#x1F4AC;</span>
            <span>질문하기</span>
          </button>
        </div>
      </div>

      {/* Ask panel (toggle) */}
      {showAskPanel && (
        <AskAgentPanel
          token={token}
          onClose={() => setShowAskPanel(false)}
        />
      )}

      {/* World Map - 2x3 grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {GRID_LOCATIONS.map((loc) => {
          const cellAgents = locMap[loc] ?? [];
          const activeConv = findConversationAtLocation(
            conversations,
            cellAgents
          );
          return (
            <LocationCell
              key={loc}
              locationKey={loc}
              agents={cellAgents}
              activeConversation={activeConv}
            />
          );
        })}
      </div>

      {/* Conversation Log */}
      <div className="rounded-xl border border-gray-700 bg-gray-900 p-4">
        <h3 className="mb-3 text-sm font-bold text-white">
          최근 대화 기록
        </h3>
        <ConversationLog conversations={conversations} />
      </div>

      {/* Error toast (non-blocking) */}
      {error && world && (
        <div className="rounded-lg border border-yellow-800/40 bg-yellow-900/10 px-3 py-2 text-xs text-yellow-400">
          폴링 오류: {error}
        </div>
      )}
    </div>
  );
}
