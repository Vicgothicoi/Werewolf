/** API 前缀，生产环境由 Nginx 反代 /api -> 后端 :8000 */
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

/** 拼接 REST API 路径，例如 apiUrl("/health") -> "/api/health" */
export function apiUrl(path: string): string {
    const normalized = path.startsWith("/") ? path : `/${path}`;
    return `${API_BASE.replace(/\/$/, "")}${normalized}`;
}

/** WebSocket 地址：默认同域 /ws，可通过 VITE_WS_URL 覆盖 */
export function wsUrl(): string {
    const override = import.meta.env.VITE_WS_URL as string | undefined;
    if (override) return override;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws`;
}
