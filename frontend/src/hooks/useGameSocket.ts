import { useState, useEffect, useCallback, useRef } from "react";
import type { GameMessage } from "../types";
import type { GameParams } from "../components/GameControls";

const WS_URL = "ws://localhost:8000/ws";
const API_URL = "http://localhost:8000";
const MSG_INTERVAL_MS = 2000;  // 消息间最小间隔
const TYPING_SPEED_MS = 30;    // 每个字符的间隔（毫秒）

type ConnectionStatus = "connecting" | "connected" | "disconnected";

interface UseGameSocketReturn {
    messages: GameMessage[];
    status: ConnectionStatus;
    isRunning: boolean;
    isWaiting: boolean;  // 队列已空但游戏仍在进行，显示等待指示器
    isTyping: boolean;   // 当前正在逐字输出最后一条消息
    startGame: (params: GameParams) => Promise<void>;
    clearMessages: () => void;
}

export function useGameSocket(): UseGameSocketReturn {
    const [messages, setMessages] = useState<GameMessage[]>([]);
    const [status, setStatus] = useState<ConnectionStatus>("disconnected");
    const [isRunning, setIsRunning] = useState(false);
    const [isWaiting, setIsWaiting] = useState(false);
    const [isTyping, setIsTyping] = useState(false);

    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    // 待显示的消息队列（收到但还没开始输出的）
    const queueRef = useRef<GameMessage[]>([]);
    // 是否正在执行出队/逐字输出，避免重复启动
    const isFlushingRef = useRef(false);
    // 上一条消息开始显示的时间戳（用于计算下一条的延迟）
    const lastShownAtRef = useRef<number>(0);
    // 当前逐字输出的 interval id，用于清理
    const typingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // 逐字展开一条消息，完成后调用 onDone
    const typeMessage = useCallback((msg: GameMessage, onDone: () => void) => {
        const fullText = msg.content;
        let charIdx = 0;

        // 先 push 一条空内容的占位消息
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

    // 从队列里逐条取出消息，每条之间至少间隔 MSG_INTERVAL_MS
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
            if (!msg) {
                isFlushingRef.current = false;
                return;
            }
            lastShownAtRef.current = Date.now();
            setIsWaiting(false);

            // 逐字输出，完成后再处理下一条
            typeMessage(msg, () => {
                lastShownAtRef.current = Date.now();
                flushQueue();
            });
        }, delay);
    }, [typeMessage]);

    // 收到新消息时入队，并在没有 flush 进行时启动 flush
    const enqueue = useCallback((msg: GameMessage) => {
        queueRef.current.push(msg);
        setIsWaiting(false); // 有新消息进来，取消等待状态
        if (!isFlushingRef.current) {
            isFlushingRef.current = true;
            flushQueue();
        }
    }, [flushQueue]);

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

        ws.onmessage = (event: MessageEvent) => {
            try {
                const data = JSON.parse(event.data as string);

                // 游戏结束事件：重置运行状态
                if (data.type === "game_over") {
                    // 等队列和逐字输出都完成后再关闭 isRunning
                    // 用轮询检查，避免在消息还没显示完时就隐藏等待指示器
                    const waitForFlush = () => {
                        if (isFlushingRef.current || typingIntervalRef.current) {
                            setTimeout(waitForFlush, 200);
                        } else {
                            setIsRunning(false);
                            setIsWaiting(false);
                        }
                    };
                    waitForFlush();
                    return;
                }

                const msg = data as GameMessage;
                enqueue(msg);
            } catch {
                // 忽略非 JSON 消息
            }
        };

        ws.onclose = () => {
            setStatus("disconnected");
            setIsRunning(false);
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
    }, [enqueue]);

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
        // flush 结束且游戏在跑 → 等待下一条消息
        const timer = setTimeout(() => {
            if (!isFlushingRef.current && isRunning) {
                setIsWaiting(true);
            }
        }, MSG_INTERVAL_MS);
        return () => clearTimeout(timer);
    }, [messages, isRunning]);

    const startGame = useCallback(async (params: GameParams) => {
        const query = new URLSearchParams({
            player_num: String(params.player_num),
            shuffle: String(params.shuffle),
            use_reflection: String(params.use_reflection),
            use_experience: String(params.use_experience),
        });

        const res = await fetch(`${API_URL}/game/start?${query}`, {
            method: "POST",
        });

        if (!res.ok) {
            throw new Error(`启动失败：${res.status}`);
        }

        // 清空上一局状态
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
        setIsRunning(true);
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
    }, []);

    return { messages, status, isRunning, isWaiting, isTyping, startGame, clearMessages };
}
