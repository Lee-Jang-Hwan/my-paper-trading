"use client";

import { useState, useCallback } from "react";
import { askAgent } from "@/services/api";
import {
  type AgentType,
  type AskAgentResponse,
  AGENT_INFO,
} from "@/types/agent";

interface AskAgentPanelProps {
  token: string | null;
  onClose?: () => void;
}

export default function AskAgentPanel({ token, onClose }: AskAgentPanelProps) {
  const [selectedAgent, setSelectedAgent] = useState<AgentType | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskAgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    if (!selectedAgent || !question.trim()) return;

    setLoading(true);
    setError(null);
    setAnswer(null);

    try {
      const res = await askAgent(token, selectedAgent, question.trim());
      setAnswer(res);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "질문 전송에 실패했습니다."
      );
    } finally {
      setLoading(false);
    }
  }, [token, selectedAgent, question]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const agentTypes = Object.keys(AGENT_INFO) as AgentType[];

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-gray-700 bg-gray-900 p-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-white">
          AI 에이전트에게 질문하기
        </h3>
        {onClose && (
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
            aria-label="닫기"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>

      {/* Agent Selection */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {agentTypes.map((type) => {
          const info = AGENT_INFO[type];
          const isSelected = selectedAgent === type;
          return (
            <button
              key={type}
              onClick={() => {
                setSelectedAgent(type);
                setAnswer(null);
                setError(null);
              }}
              className={`flex flex-col items-center gap-1.5 rounded-lg border p-3 transition-all ${
                isSelected
                  ? `border-gray-500 ${info.bgColor} ring-1 ring-gray-500`
                  : "border-gray-700 bg-gray-800 hover:border-gray-600 hover:bg-gray-800/80"
              }`}
            >
              <span className="text-2xl">{info.emoji}</span>
              <span
                className={`text-sm font-semibold ${
                  isSelected ? info.color : "text-gray-300"
                }`}
              >
                {info.name}
              </span>
              <span className="text-[11px] text-gray-500">{info.role}</span>
            </button>
          );
        })}
      </div>

      {/* Question Input */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-gray-400">
          {selectedAgent
            ? `${AGENT_INFO[selectedAgent].name}에게 질문`
            : "에이전트를 선택하세요"}
        </label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            selectedAgent
              ? `${AGENT_INFO[selectedAgent].name}에게 궁금한 것을 물어보세요...`
              : "먼저 에이전트를 선택하세요"
          }
          disabled={!selectedAgent}
          rows={3}
          className="w-full resize-none rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white placeholder-gray-500 outline-none transition-colors focus:border-gray-500 focus:ring-1 focus:ring-gray-500 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      {/* Submit Button */}
      <button
        onClick={handleSubmit}
        disabled={!selectedAgent || !question.trim() || loading}
        className="flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
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
            <span>답변 생성 중...</span>
          </>
        ) : (
          <span>질문하기</span>
        )}
      </button>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-800/50 bg-red-900/20 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Answer */}
      {answer && (
        <div className="space-y-2 rounded-lg border border-gray-700 bg-gray-800 p-4">
          <div className="flex items-center gap-2">
            <span className="text-lg">
              {AGENT_INFO[answer.agent_type].emoji}
            </span>
            <span
              className={`text-sm font-semibold ${
                AGENT_INFO[answer.agent_type].color
              }`}
            >
              {answer.agent_name}
            </span>
            <span className="text-xs text-gray-500">의 답변</span>
          </div>

          <div className="text-xs text-gray-500">
            Q: {answer.question}
          </div>

          <div className="whitespace-pre-wrap text-sm leading-relaxed text-gray-200">
            {answer.answer}
          </div>
        </div>
      )}
    </div>
  );
}
