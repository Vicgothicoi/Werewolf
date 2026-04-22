import { useGameSocket } from "./hooks/useGameSocket";
import MessageList from "./components/MessageList";
import GameControls from "./components/GameControls";
import HumanInput from "./components/HumanInput";
import type { GameParams } from "./components/GameControls";

const STATUS_DOT: Record<string, string> = {
    connected: "bg-green-400",
    connecting: "bg-yellow-400 animate-pulse",
    disconnected: "bg-red-400",
};

const STATUS_LABEL: Record<string, string> = {
    connected: "已连接",
    connecting: "连接中…",
    disconnected: "未连接",
};

export default function App() {
    const {
        messages, status, isRunning, isWaiting, isTyping,
        awaitInputInstruction, humanRole,
        startGame, sendInput,
    } = useGameSocket();

    const handleStart = async (params: GameParams) => {
        try {
            await startGame(params);
        } catch (err) {
            console.error(err);
        }
    };

    return (
        <div className="flex flex-col h-screen bg-gray-50">
            {/* 顶部标题栏 */}
            <header className="flex items-center justify-between px-5 py-3 bg-white border-b border-gray-200 shadow-sm">
                <div className="flex items-center gap-2">
                    <span className="text-xl">🐺</span>
                    <h1 className="text-base font-semibold text-gray-900">
                        {humanRole ? `狼人杀 · ${humanRole}` : "狼人杀 · 观战"}
                    </h1>
                </div>

                <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${STATUS_DOT[status]}`} />
                    <span className="text-xs text-gray-500">{STATUS_LABEL[status]}</span>
                    {isRunning && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-600 font-medium">
                            游戏进行中
                        </span>
                    )}
                </div>
            </header>

            {/* 消息区域 */}
            <MessageList
                messages={messages}
                isWaiting={isWaiting && !awaitInputInstruction}
                isTyping={isTyping}
                humanRole={humanRole}
            />

            {/* 人类玩家输入框（等待输入时显示，覆盖底部控制栏） */}
            {awaitInputInstruction ? (
                <HumanInput
                    instruction={awaitInputInstruction}
                    onSubmit={sendInput}
                />
            ) : (
                <GameControls
                    onStart={handleStart}
                    isRunning={isRunning}
                    isConnected={status === "connected"}
                />
            )}
        </div>
    );
}
