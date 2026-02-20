/**
 * WebSocket 기본 URL을 결정합니다.
 *
 * Next.js rewrite는 WS 프록시를 지원하지 않으므로 백엔드 직접 연결.
 * NEXT_PUBLIC_WS_URL > NEXT_PUBLIC_API_URL > 자동 탐지 순으로 결정.
 */
export function getWsBaseUrl(): string {
  if (typeof window === "undefined") return "";

  const wsUrl = process.env.NEXT_PUBLIC_WS_URL ?? "";
  if (wsUrl) return wsUrl;

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
  if (apiUrl) {
    return apiUrl.replace(/^https:/, "wss:").replace(/^http:/, "ws:");
  }

  // 개발환경 fallback
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const hostname = window.location.hostname;
  if (window.location.port === "3000") {
    return `${protocol}://${hostname}:8000`;
  }
  return `${protocol}://${window.location.host}`;
}
