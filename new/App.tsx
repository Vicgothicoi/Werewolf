import { useGameSocket } from "./hooks/useGameSocket";
import MessageList from "./components/MessageList";
import GameControls from "./components/GameControls";
import HumanInput from "./components/HumanInput";
import GameSidebar from "./components/GameSidebar";
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
        currentGameId, historyMessages, viewingGameId,
        startGame, sendInput, viewGame, exitHistory,
    } = useGameSocket();

    const handleStart = async (params: GameParams) => {
        try {
            await startGame(params);
        } catch (err) {
            console.error(err);
        }
    };

    // 历史查看模式下显示历史消息，否则显示实时消息
    const displayMessages = viewingGameId ? historyMessages : messages;

    return (
        <div className="flex flex-col h-screen bg-gray-50">
            {/* 顶部标题栏 */}
            <header className="flex items-center justify-between px-5 py-3 bg-white border-b border-gray-200 shadow-sm flex-shrink-0">
                <div className="flex items-center gap-2">
                    <span className="text-xl">🐺</span>
                    <h1 className="text-base font-semibold text-gray-900">
                        {viewingGameId
                            ? `历史对局 #${viewingGameId}`
                            : humanRole
                                ? `狼人杀 · ${humanRole}`
                                : "狼人杀 · 观战"}
                    </h1>
                </div>

                <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${STATUS_DOT[status]}`} />
                    <span className="text-xs text-gray-500">{STATUS_LABEL[status]}</span>
                    {isRunning && !viewingGameId && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-600 font-medium">
                            游戏进行中
                        </span>
                    )}
                </div>
            </header>

            {/* 主体：侧边栏 + 消息区 */}
            <div className="flex flex-1 min-h-0">
                {/* 左侧历史对局侧边栏 */}
                <GameSidebar
                    currentGameId={currentGameId}
                    viewingGameId={viewingGameId}
                    onViewGame={viewGame}
                    onExitHistory={exitHistory}
                    isRunning={isRunning}
                />

                {/* 右侧消息区 + 底部控制栏 */}
                <div className="flex flex-col flex-1 min-w-0">
                    <MessageList
                        messages={displayMessages}
                        isWaiting={!viewingGameId && isWaiting && !awaitInputInstruction}
                        isTyping={!viewingGameId && isTyping}
                        humanRole={humanRole}
                    />

                    {/* 历史查看模式不显示控制栏 */}
                    {!viewingGameId && (
                        awaitInputInstruction ? (
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
                        )
                    )}
                </div>
            </div>
        </div>
    );
}
