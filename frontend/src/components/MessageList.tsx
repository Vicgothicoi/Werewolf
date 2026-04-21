import { useEffect, useRef, type ReactNode } from "react";
import type { GameMessage } from "../types";
import MessageBubble from "./MessageBubble";

// 检测消息内容是否为昼夜切换的 Moderator 公告，返回分隔线标签或 null
// 对应 STEP_INSTRUCTIONS 中 step 0 和 step 11 的固定开头
let nightCount = 0;
let dayCount = 0;

function getPhaseLabel(msg: GameMessage): string | null {
    if (msg.role !== "Moderator") return null;
    // 去掉时间戳前缀后匹配
    const content = msg.content.replace(/^\d+\s*\|\s*/, "");
    if (content.startsWith("It's dark")) {
        nightCount += 1;
        return `第 ${nightCount} 夜`;
    }
    if (content.startsWith("It's daytime")) {
        dayCount += 1;
        return `第 ${dayCount} 天`;
    }
    return null;
}

interface Props {
    messages: GameMessage[];
    isWaiting: boolean;
    isTyping: boolean;
}

export default function MessageList({ messages, isWaiting, isTyping }: Props) {
    const bottomRef = useRef<HTMLDivElement>(null);

    // 新消息到来时自动滚动到底部
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    if (messages.length === 0) {
        return (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
                等待游戏开始…
            </div>
        );
    }

    // 重置计数器，每次重新渲染完整列表时从头计数
    nightCount = 0;
    dayCount = 0;

    const items: ReactNode[] = [];

    messages.forEach((msg, idx) => {
        const label = getPhaseLabel(msg);
        if (label) {
            items.push(
                <div
                    key={`divider-${idx}`}
                    className="flex items-center gap-3 my-3 px-2"
                >
                    <div className="flex-1 h-px bg-gray-200" />
                    <span className="text-xs text-gray-400 font-medium whitespace-nowrap">
                        {label}
                    </span>
                    <div className="flex-1 h-px bg-gray-200" />
                </div>
            );
        }
        items.push(
            <MessageBubble
                key={`msg-${idx}`}
                message={msg}
                isTyping={isTyping && idx === messages.length - 1}
            />
        );
    });

    return (
        <div className="flex-1 overflow-y-auto px-4 py-2">
            {items}
            {/* 等待指示器：上一条消息已显示，下一条还未到达 */}
            {isWaiting && (
                <div className="flex gap-3 py-2">
                    <div className="w-9 h-9 rounded-full bg-gray-200 flex-shrink-0" />
                    <div className="flex items-center px-3 py-2 rounded-2xl rounded-tl-sm bg-white border border-gray-200 shadow-sm">
                        <span className="flex gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:0ms]" />
                            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:150ms]" />
                            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:300ms]" />
                        </span>
                    </div>
                </div>
            )}
            <div ref={bottomRef} />
        </div>
    );
}
