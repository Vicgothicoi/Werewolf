import { useEffect, useState } from "react";

const API_URL = "http://localhost:8000";

interface GameMeta {
    game_id: string;
    player_num: string;
    add_human: string;
    started_at: string;
    winner: string;
    win_reason: string;
}

interface Props {
    currentGameId: string | null;       // 当前正在进行的局 id，用于高亮
    viewingGameId: string | null;       // 当前正在查看的历史局 id
    onViewGame: (gameId: string) => void;
    onExitHistory: () => void;
    isRunning: boolean;
}

const WINNER_BADGE: Record<string, string> = {
    "good guys": "bg-blue-100 text-blue-700",
    "werewolf": "bg-red-100 text-red-700",
    "": "bg-gray-100 text-gray-500",
};

const WINNER_LABEL: Record<string, string> = {
    "good guys": "好人胜",
    "werewolf": "狼人胜",
    "": "进行中",
};

export default function GameSidebar({
    currentGameId,
    viewingGameId,
    onViewGame,
    onExitHistory,
    isRunning,
}: Props) {
    const [games, setGames] = useState<GameMeta[]>([]);
    const [loading, setLoading] = useState(false);

    const fetchGames = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_URL}/games`);
            if (res.ok) setGames(await res.json());
        } catch {
            // Redis 未启动时静默失败
        } finally {
            setLoading(false);
        }
    };

    // 初始加载 + 每局结束后刷新
    useEffect(() => {
        fetchGames();
    }, [isRunning]); // isRunning 从 true→false 时（游戏结束）触发刷新

    return (
        <aside className="w-56 flex-shrink-0 flex flex-col bg-white border-r border-gray-200">
            {/* 标题 */}
            <div className="px-4 py-3 border-b border-gray-200">
                <h2 className="text-sm font-semibold text-gray-700">历史对局</h2>
            </div>

            {/* 对局列表 */}
            <div className="flex-1 overflow-y-auto py-1">
                {loading && (
                    <p className="text-xs text-gray-400 px-4 py-2">加载中…</p>
                )}
                {!loading && games.length === 0 && (
                    <p className="text-xs text-gray-400 px-4 py-2">暂无历史对局</p>
                )}
                {games.filter((g) => g.game_id).map((g) => {
                    const isViewing = viewingGameId === g.game_id;
                    const isCurrent = currentGameId === g.game_id;
                    return (
                        <button
                            key={g.game_id}
                            onClick={() => onViewGame(g.game_id)}
                            className={`w-full text-left px-4 py-2.5 hover:bg-gray-50 transition-colors
                                ${isViewing ? "bg-indigo-50 border-l-2 border-indigo-500" : "border-l-2 border-transparent"}
                            `}
                        >
                            {/* 时间 */}
                            <p className="text-xs text-gray-400 mb-0.5">
                                {g.started_at.replace("T", " ")}
                            </p>
                            {/* 人数 + 胜负 */}
                            <div className="flex items-center gap-1.5">
                                <span className="text-xs text-gray-600">
                                    {g.player_num} 人局
                                    {g.add_human === "True" ? " · 含人类" : ""}
                                </span>
                                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${WINNER_BADGE[g.winner] ?? WINNER_BADGE[""]}`}>
                                    {WINNER_LABEL[g.winner] ?? "未知"}
                                </span>
                                {isCurrent && (
                                    <span className="text-xs px-1 py-0.5 rounded bg-indigo-100 text-indigo-600">当前</span>
                                )}
                            </div>
                        </button>
                    );
                })}
            </div>

            {/* 退出历史查看按钮 */}
            {viewingGameId && (
                <div className="px-4 py-3 border-t border-gray-200">
                    <button
                        onClick={onExitHistory}
                        className="w-full text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                    >
                        ← 返回当前游戏
                    </button>
                </div>
            )}
        </aside>
    );
}
