import { useState, useEffect, useCallback, useRef } from "react";
import type { GameMessage } from "../types";
import type { GameParams } from "../components/GameControls";

const WS_URL = "ws://localhost:8000/ws";
const API_URL = "http://localhost:8000";
const MSG_INTERVAL_MS = 2000;
const TYPING_SPEED_MS = 30;

type ConnectionStatus = "connecting" | "connected" | "disconnected";

interface UseGameSocketReturn {
    messages: GameMessage[];
    status: ConnectionStatus;
    isRunning: boolean;
    isWaiting: boolean;
    isTyping: boolean;
    awaitInputInstruction: string | null;
    humanRole: string | null;
    currentGameId: string | null;
    historyMessages: GameMessage[];
    viewingGameId: string | null;
    startGame: (params: GameParams) => Promise<void>;
    sendInput: (text: string) => void;
    viewGame: (gameId: string) => Promise<void>;
    exitHistory: () => void;
    clearMessages: () => void;
}

export function useGameSocket(): UseGameSocketReturn {
    const [messages, setMessages] = useState<GameMessage[]>([]);
    const [status, setStatus] = useState<ConnectionStatus>("disconnected");
    const [isRunning, setIsRunning] = useState(false);
    const [isWaiting, setIsWaiting] = useState(false);
    const [isTyping, setIsTyping] = useState(false);
    const [awaitInputInstruction, setAwaitInputInstruction] = useState<string | null>(null);
    const [humanRole, setHumanRole] = useState<string | null>(null);
    const [currentGameId, setCurrentGameId] = useState<string | null>(null);
    const [historyMessages, setHistoryMessages] = useState<GameMessage[]>([]);
    const [viewingGameId, setViewingGameId] = useState<string | null>(null);

    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const queueRef = useRef<GameMessage[]>([]);
    const isFlushingRef = useRef(false);
    const lastShownAtRef = useRef<number>(0);
    const typingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // 用 ref 持有 onmessage 处理函数，让 connect 的依赖数组可以为 []
    // 每次渲染后更新 ref，确保 onmessage 始终使用最新的 enqueue 等函数
    const onMessageRef = useRef<(event: MessageEvent) => void>(() => { });

    // ── 消息队列逻辑（不参与 connect 的依赖链）────────────────────

    const typeMessage = useCallback((msg: GameMessage, onDone: () => void) => {
        const fullText = msg.content;
        let charIdx = 0;
        setMessages((prev) => [...prev, { ...msg, content: "" }]);
        setIsTyping(true);
        typingIntervalRef.current = setInterval(() => {
            charIdx += 1;
            setMessages((prev) => {
                const next = [...prev];
                next[next.length - 1] = { ...msg, content: fullText.slice(0, charIdx) };
                return next;
            });
            if (charIdx >= fullText.length) {
                clearInterval(typingIntervalRef.current!);
                typingIntervalRef.current = null;
                setIsTyping(false);
                onDone();
            }
        }, TYPING_SPEED_MS);
    }, []);

    const flushQueue = useCallback(() => {
        if (queueRef.current.length === 0) {
            isFlushingRef.current = false;
            return;
        }
        const now = Date.now();
        const elapsed = now - lastShownAtRef.current;
        const delay = Math.max(0, MSG_INTERVAL_MS - elapsed);
        setTimeout(() => {
            const msg = queueRef.current.shift();
            if (!msg) { isFlushingRef.current = false; return; }
            lastShownAtRef.current = Date.now();
            setIsWaiting(false);
            typeMessage(msg, () => {
                lastShownAtRef.current = Date.now();
                flushQueue();
            });
        }, delay);
    }, [typeMessage]);

    const enqueue = useCallback((msg: GameMessage) => {
        queueRef.current.push(msg);
        setIsWaiting(false);
        if (!isFlushingRef.current) {
            isFlushingRef.current = true;
            flushQueue();
        }
    }, [flushQueue]);

    // 每次渲染后把最新的 onmessage 处理逻辑同步到 ref
    useEffect(() => {
        onMessageRef.current = (event: MessageEvent) => {
            try {
                const data = JSON.parse(event.data as string);

                if (data.type === "game_over") {
                    const waitForFlush = () => {
                        if (isFlushingRef.current || typingIntervalRef.current) {
                            setTimeout(waitForFlush, 200);
                        } else {
                            setIsRunning(false);
                            setIsWaiting(false);
                            setAwaitInputInstruction(null);
                            setHumanRole(null);
                        }
                    };
                    waitForFlush();
                    return;
                }

                if (data.type === "player_info") {
                    setHumanRole(data.profile as string);
                    return;
                }

                if (data.type === "await_input") {
                    setIsWaiting(false);
                    setAwaitInputInstruction(data.instruction as string);
                    return;
                }

                enqueue(data as GameMessage);
            } catch {
                // 忽略非 JSON 消息
            }
        };
    }); // 无依赖数组：每次渲染都更新

    // ── WebSocket 连接（依赖数组为 []，永不重建）─────────────────

    const connect = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) return;

        setStatus("connecting");
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
            setStatus("connected");
            if (reconnectTimer.current) {
                clearTimeout(reconnectTimer.current);
                reconnectTimer.current = null;
            }
        };

        // 通过 ref 间接调用，始终使用最新版本，不产生依赖
        ws.onmessage = (event: MessageEvent) => {
            onMessageRef.current(event);
        };

        ws.onclose = () => {
            setStatus("disconnected");
            setIsWaiting(false);
            setIsTyping(false);
            if (typingIntervalRef.current) {
                clearInterval(typingIntervalRef.current);
                typingIntervalRef.current = null;
            }
            wsRef.current = null;
            reconnectTimer.current = setTimeout(connect, 3000);
        };

        ws.onerror = () => {
            ws.close();
        };
    }, []); // 空依赖：connect 永不重建，WebSocket 连接稳定

    useEffect(() => {
        connect();
        return () => {
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
            wsRef.current?.close();
        };
    }, [connect]);

    // 队列消费完后，若游戏仍在运行则切换到等待状态
    useEffect(() => {
        if (!isRunning) return;
        if (isFlushingRef.current) return;
        const timer = setTimeout(() => {
            if (!isFlushingRef.current && isRunning) setIsWaiting(true);
        }, MSG_INTERVAL_MS);
        return () => clearTimeout(timer);
    }, [messages, isRunning]);

    // ── 游戏控制 ─────────────────────────────────────────────────

    const startGame = useCallback(async (params: GameParams) => {
        // 在 fetch 之前清空上一局状态
        queueRef.current = [];
        isFlushingRef.current = false;
        lastShownAtRef.current = 0;
        if (typingIntervalRef.current) {
            clearInterval(typingIntervalRef.current);
            typingIntervalRef.current = null;
        }
        setMessages([]);
        setIsWaiting(false);
        setIsTyping(false);
        setAwaitInputInstruction(null);

        const query = new URLSearchParams({
            player_num: String(params.player_num),
            shuffle: String(params.shuffle),
            use_reflection: String(params.use_reflection),
            use_experience: String(params.use_experience),
            add_human: String(params.add_human),
        });

        const res = await fetch(`${API_URL}/game/start?${query}`, { method: "POST" });
        if (!res.ok) throw new Error(`启动失败：${res.status}`);

        const body = await res.json() as { status: string; game_id?: string };
        setCurrentGameId(body.game_id ?? null);
        setViewingGameId(null);
        // fetch 返回后不清 awaitInputInstruction / humanRole，避免覆盖已收到的事件
        setIsRunning(true);
    }, []);

    const sendInput = useCallback((text: string) => {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(text);
            setAwaitInputInstruction(null);
        } else {
            console.warn("[sendInput] WebSocket not open, readyState:", ws?.readyState);
        }
    }, []);

    const viewGame = useCallback(async (gameId: string) => {
        try {
            const res = await fetch(`${API_URL}/games/${gameId}`);
            if (!res.ok) return;
            const msgs = await res.json() as GameMessage[];
            setHistoryMessages(msgs);
            setViewingGameId(gameId);
        } catch { /* 静默失败 */ }
    }, []);

    const exitHistory = useCallback(() => {
        setViewingGameId(null);
        setHistoryMessages([]);
    }, []);

    const clearMessages = useCallback(() => {
        queueRef.current = [];
        isFlushingRef.current = false;
        if (typingIntervalRef.current) {
            clearInterval(typingIntervalRef.current);
            typingIntervalRef.current = null;
        }
        setMessages([]);
        setIsWaiting(false);
        setIsTyping(false);
        setAwaitInputInstruction(null);
    }, []);

    return {
        messages, status, isRunning, isWaiting, isTyping,
        awaitInputInstruction, humanRole,
        currentGameId, historyMessages, viewingGameId,
        startGame, sendInput, viewGame, exitHistory, clearMessages,
    };
}
