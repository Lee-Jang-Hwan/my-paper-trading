"use client";

import { useEffect, useRef, useCallback } from "react";
import { useAgentStore } from "@/stores/agent-store";
import { useAuth } from "@clerk/nextjs";
import type { AgentEvent } from "@/types/agent";

/**
 * WebSocket URL: connect directly to backend (Next.js rewrites don't proxy WS)
 */
function getWsBaseUrl(): string {
  if (typeof window === "undefined") return "";

  // 환경변수로 지정된 경우 사용
  const envWs = (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_WS_URL) || "";
  if (envWs) return envWs;

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const hostname = window.location.hostname;
  if (window.location.port === "3000") {
    return `${protocol}://${hostname}:8000`;
  }
  return `${protocol}://${window.location.host}`;
}

const MAX_RECONNECT_DELAY = 30_000;
const INITIAL_RECONNECT_DELAY = 1_000;
const PING_INTERVAL = 25_000;

export function useAgentWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(INITIAL_RECONNECT_DELAY);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  const tokenRef = useRef<string | null>(null);

  const { getToken } = useAuth();
  const { setWsConnected, handleAgentEvent } = useAgentStore();

  const cleanup = useCallback(() => {
    if (pingTimer.current) {
      clearInterval(pingTimer.current);
      pingTimer.current = null;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const connect = useCallback(async () => {
    if (!mountedRef.current || typeof window === "undefined") return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    cleanup();

    // 인증 토큰 획득
    try {
      const token = await getToken();
      if (!token || !mountedRef.current) return;
      tokenRef.current = token;
    } catch {
      return;
    }

    try {
      const wsBase = getWsBaseUrl();
      const ws = new WebSocket(`${wsBase}/ws/agents?token=${encodeURIComponent(tokenRef.current!)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setWsConnected(true);
        reconnectDelay.current = INITIAL_RECONNECT_DELAY;

        pingTimer.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send("ping");
          }
        }, PING_INTERVAL);
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(event.data) as AgentEvent;
          handleAgentEvent(data);
        } catch {
          // malformed message
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setWsConnected(false);
        cleanup();

        const delay = reconnectDelay.current;
        reconnectDelay.current = Math.min(delay * 2, MAX_RECONNECT_DELAY);
        reconnectTimer.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      if (!mountedRef.current) return;
      const delay = reconnectDelay.current;
      reconnectDelay.current = Math.min(delay * 2, MAX_RECONNECT_DELAY);
      reconnectTimer.current = setTimeout(connect, delay);
    }
  }, [setWsConnected, handleAgentEvent, cleanup, getToken]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      cleanup();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setWsConnected(false);
    };
  }, [connect, cleanup, setWsConnected]);
}
