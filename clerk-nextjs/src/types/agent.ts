// ============================================================
// Agent domain types (Generative Agents architecture)
// ============================================================

/** Agent type identifiers */
export type AgentType = "trend" | "advisor" | "news" | "portfolio";

/** Runtime state of a single agent */
export interface AgentState {
  agent_type: AgentType;
  name: string;
  location: string;
  action: string;
  action_description: string;
  is_in_conversation: boolean;
  conversation_partner: string | null;
}

/** Single message inside a conversation */
export interface ConversationMessage {
  turn: number;
  round?: number;
  speaker: string;
  speaker_type: string;
  content: string;
  timestamp: string;
}

/** A recorded conversation between agents */
export interface AgentConversation {
  initiator?: string;
  target?: string;
  topic: string;
  messages: ConversationMessage[];
  conclusion?: string;
  meeting_type?: string;
  participants?: string[];
}

/** Full world snapshot returned by GET /api/agents/world */
export interface WorldState {
  tick_count: number;
  running: boolean;
  agents: AgentState[];
  recent_conversations: AgentConversation[];
  gemini_status: {
    available: boolean;
    tokens_used: number;
  };
}

/** Response from POST /api/agents/ask */
export interface AskAgentResponse {
  agent_type: AgentType;
  agent_name: string;
  question: string;
  answer: string;
}

// ---- Static metadata ---------------------------------------------------

export const AGENT_INFO: Record<
  AgentType,
  {
    name: string;
    emoji: string;
    color: string;
    bgColor: string;
    role: string;
    homeLocation: string;
  }
> = {
  trend: {
    name: "한눈이",
    emoji: "🔍",
    color: "text-blue-400",
    bgColor: "bg-blue-500/20",
    role: "시장 동향 분석",
    homeLocation: "market_board",
  },
  advisor: {
    name: "슬기",
    emoji: "📊",
    color: "text-emerald-400",
    bgColor: "bg-emerald-500/20",
    role: "투자 자문",
    homeLocation: "analysis_desk",
  },
  news: {
    name: "번개",
    emoji: "⚡",
    color: "text-yellow-400",
    bgColor: "bg-yellow-500/20",
    role: "뉴스 캐치",
    homeLocation: "news_terminal",
  },
  portfolio: {
    name: "밸런스",
    emoji: "⚖️",
    color: "text-purple-400",
    bgColor: "bg-purple-500/20",
    role: "포트폴리오 최적화",
    homeLocation: "portfolio_board",
  },
};

export const LOCATION_LABELS: Record<string, string> = {
  market_board: "시장 전광판",
  analysis_desk: "분석 데스크",
  news_terminal: "뉴스 터미널",
  portfolio_board: "포트폴리오 보드",
  meeting_table: "미팅 테이블",
  user_desk: "사용자 데스크",
};

export const ACTION_LABELS: Record<string, { label: string; icon: string }> = {
  idle: { label: "대기", icon: "💤" },
  observe: { label: "관찰", icon: "👀" },
  analyze: { label: "분석", icon: "📖" },
  talk: { label: "대화", icon: "💬" },
  alert: { label: "알림", icon: "⚠️" },
  write: { label: "작성", icon: "✍️" },
  think: { label: "고민", icon: "💡" },
  move: { label: "이동", icon: "🏃" },
  excited: { label: "발견!", icon: "😲" },
};

// ---- WebSocket event types ------------------------------------------------

export type AgentEventType =
  | "conversation_start"
  | "turn_message"
  | "conversation_end"
  | "meeting_start"
  | "meeting_end"
  | "pong";

export interface AgentEvent {
  type: AgentEventType;
  conversation_id?: string;
  data?: Record<string, unknown>;
  timestamp?: string;
}

// ---- Live conversation state -----------------------------------------------

export interface LiveConversation {
  conversation_id: string;
  topic: string;
  participants: { agent_type: string; name: string }[];
  messages: ConversationMessage[];
  conclusion?: string;
  status: "active" | "completed";
  maxTurns?: number;
  meetingType?: string;
}

// ---- Debate request/response -----------------------------------------------

export interface DebateRequest {
  topic: string;
  stock_code?: string;
  stock_name?: string;
}

export interface DebateResponse {
  status: string;
  conversation_id?: string;
  topic?: string;
  participants?: { agent_type: string; name: string }[];
  message?: string;
  remaining_seconds?: number;
}

// ---- Opinion types ---------------------------------------------------------

export interface AgentOpinion {
  agent_type: AgentType;
  agent_name: string;
  opinion: string;
  sentiment: "bullish" | "bearish" | "neutral";
  confidence: number;
  key_points: string[];
}

export interface OpinionSummaryResponse {
  topic: string;
  opinions: AgentOpinion[];
  consensus: string;
  agreement_level: "strong" | "moderate" | "divided" | "mixed";
}
