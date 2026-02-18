import { create } from "zustand";
import type {
  WorldState,
  LiveConversation,
  ConversationMessage,
  AgentEvent,
  OpinionSummaryResponse,
} from "@/types/agent";

// ============================================================
// Agent Store – Zustand v5
// ============================================================

interface AgentStoreState {
  /* ---- data ---- */
  worldState: WorldState | null;
  liveConversations: Map<string, LiveConversation>;
  activeDebateId: string | null;
  opinionSummary: OpinionSummaryResponse | null;
  opinionLoading: boolean;

  /* ---- ws ---- */
  wsConnected: boolean;

  /* ---- actions ---- */
  setWorldState: (state: WorldState) => void;
  setWsConnected: (connected: boolean) => void;
  setActiveDebateId: (id: string | null) => void;
  setOpinionSummary: (summary: OpinionSummaryResponse | null) => void;
  setOpinionLoading: (loading: boolean) => void;

  /* ---- ws event handlers ---- */
  handleAgentEvent: (event: AgentEvent) => void;
}

export const useAgentStore = create<AgentStoreState>((set, get) => ({
  /* ---- initial data ---- */
  worldState: null,
  liveConversations: new Map(),
  activeDebateId: null,
  opinionSummary: null,
  opinionLoading: false,

  /* ---- ws ---- */
  wsConnected: false,

  /* ---- setters ---- */
  setWorldState: (worldState) => set({ worldState }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setActiveDebateId: (activeDebateId) => set({ activeDebateId }),
  setOpinionSummary: (opinionSummary) => set({ opinionSummary }),
  setOpinionLoading: (opinionLoading) => set({ opinionLoading }),

  /* ---- ws event handling ---- */
  handleAgentEvent: (event: AgentEvent) => {
    const { type, conversation_id: convId, data } = event;
    if (!convId && type !== "pong") return;

    const conversations = new Map(get().liveConversations);

    switch (type) {
      case "conversation_start": {
        conversations.set(convId!, {
          conversation_id: convId!,
          topic: (data?.topic as string) ?? "",
          participants: [
            {
              agent_type: data?.initiator as string,
              name: data?.initiator_name as string,
            },
            {
              agent_type: data?.target as string,
              name: data?.target_name as string,
            },
          ],
          messages: [],
          status: "active",
          maxTurns: (data?.max_turns as number) ?? 6,
        });
        set({ liveConversations: conversations });
        break;
      }

      case "meeting_start": {
        conversations.set(convId!, {
          conversation_id: convId!,
          topic: (data?.topic as string) ?? "",
          participants:
            (data?.participants as { agent_type: string; name: string }[]) ?? [],
          messages: [],
          status: "active",
          maxTurns: ((data?.total_rounds as number) ?? 2) * 4,
          meetingType: (data?.meeting_type as string) ?? "meeting",
        });
        set({ liveConversations: conversations });
        break;
      }

      case "turn_message": {
        const conv = conversations.get(convId!);
        if (conv) {
          const msg = data as unknown as ConversationMessage;
          conversations.set(convId!, {
            ...conv,
            messages: [...conv.messages, msg],
          });
          set({ liveConversations: conversations });
        }
        break;
      }

      case "conversation_end":
      case "meeting_end": {
        const conv = conversations.get(convId!);
        if (conv) {
          conversations.set(convId!, {
            ...conv,
            status: "completed",
            conclusion: (data?.conclusion as string) ?? undefined,
          });
          set({ liveConversations: conversations });

          // 완료된 토론이 activeDebate인 경우 해제
          if (get().activeDebateId === convId) {
            set({ activeDebateId: null });
          }
        }
        break;
      }

      default:
        break;
    }
  },
}));
