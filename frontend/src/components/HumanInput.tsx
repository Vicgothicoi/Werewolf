import { useState, useEffect, useRef } from "react";

interface Props {
    instruction: string;       // 后端推送的提示文字
    onSubmit: (text: string) => void;
}

export default function HumanInput({ instruction, onSubmit }: Props) {
    const [text, setText] = useState("");
    const inputRef = useRef<HTMLTextAreaElement>(null);

    // 出现时自动聚焦
    useEffect(() => {
        inputRef.current?.focus();
    }, []);

    const handleSubmit = () => {
        const trimmed = text.trim();
        if (!trimmed) return;
        onSubmit(trimmed);
        setText("");
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        // Enter 提交，Shift+Enter 换行
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    };

    return (
        <div className="border-t-2 border-indigo-300 bg-indigo-50 px-4 py-3">
            {/* 提示文字 */}
            <p className="text-xs text-indigo-600 font-medium mb-2 whitespace-pre-wrap">
                🎮 轮到你了：{instruction}
            </p>

            {/* 输入区域 */}
            <div className="flex gap-2 items-end">
                <textarea
                    ref={inputRef}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    rows={2}
                    placeholder="输入你的发言或行动…（Enter 发送，Shift+Enter 换行）"
                    className="flex-1 resize-none rounded-lg border border-indigo-300 px-3 py-2 text-sm text-gray-800 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
                <button
                    onClick={handleSubmit}
                    disabled={!text.trim()}
                    className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors
                        ${!text.trim()
                            ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                            : "bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800"
                        }`}
                >
                    发送
                </button>
            </div>
        </div>
    );
}
