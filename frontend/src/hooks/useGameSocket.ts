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
    isWaiting: boolean;
    isTyping: boolean;
    awaitInputInstruction: string | null; // 非 null 时表示正在等待人类输入
    humanRole: string | null;             // 人类玩家的 role，用于隐藏其他玩家身份
    startGame: (params: GameParams) => Promise<void>;
    sendInput: (text: string) => void;    // 发送人类玩家输入
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

                // 游戏结束事件
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

                // player_info：后端主动告知人类玩家身份
                if (data.type === "player_info") {
                    setHumanRole(data.profile as string);
                    return;
                }

                // 等待人类输入事件：暂停等待指示器，显示输入框
                if (data.type === "await_input") {
                    setIsWaiting(false);
                    setAwaitInputInstruction(data.instruction as string);
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
            setAwaitInputInstruction(null);
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
            add_human: String(params.add_human),
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
        setAwaitInputInstruction(null);
        // humanRole 不在这里重置，由 player_info 事件设置，避免覆盖已收到的值
        setIsRunning(true);
    }, []);

    // 发送人类玩家输入，通过 WebSocket 传给后端
    const sendInput = useCallback((text: string) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(text);
            setAwaitInputInstruction(null); // 关闭输入框
        }
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
        startGame, sendInput, clearMessages,
    };
}
