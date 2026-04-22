import { useState } from "react";

export type GameParams = {
    player_num: number;
    shuffle: boolean;
    use_reflection: boolean;
    use_experience: boolean;
    add_human: boolean;
};

interface Props {
    onStart: (params: GameParams) => void;
    isRunning: boolean;
    isConnected: boolean;
}

export default function GameControls({ onStart, isRunning, isConnected }: Props) {
    const [params, setParams] = useState<GameParams>({
        player_num: 5,
        shuffle: true,
        use_reflection: true,
        use_experience: false,
        add_human: false,
    });

    const handleStart = () => {
        if (!isConnected || isRunning) return;
        onStart(params);
    };

    return (
        <div className="border-t border-gray-200 bg-white px-4 py-3 flex flex-wrap items-center gap-4">
            {/* 玩家人数 */}
            <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600 whitespace-nowrap">玩家数</label>
                <select
                    className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
                    value={params.player_num}
                    onChange={(e) =>
                        setParams((p) => ({ ...p, player_num: Number(e.target.value) }))
                    }
                    disabled={isRunning}
                >
                    {[4, 5, 6, 7, 8, 9, 10].map((n) => (
                        <option key={n} value={n}>
                            {n} 人
                        </option>
                    ))}
                </select>
            </div>

            {/* 开关选项 */}
            {(
                [
                    { key: "shuffle", label: "随机身份" },
                    { key: "use_reflection", label: "反思" },
                    { key: "use_experience", label: "经验" },
                    { key: "add_human", label: "加入人类玩家" },
                ] as { key: keyof GameParams; label: string }[]
            ).map(({ key, label }) => (
                <label key={key} className="flex items-center gap-1.5 cursor-pointer">
                    <input
                        type="checkbox"
                        className="w-4 h-4 accent-indigo-500"
                        checked={params[key] as boolean}
                        onChange={(e) =>
                            setParams((p) => ({ ...p, [key]: e.target.checked }))
                        }
                        disabled={isRunning}
                    />
                    <span className="text-sm text-gray-600">{label}</span>
                </label>
            ))}

            {/* 开始按钮 */}
            <button
                onClick={handleStart}
                disabled={!isConnected || isRunning}
                className={`ml-auto px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors
          ${!isConnected
                        ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                        : isRunning
                            ? "bg-indigo-300 text-white cursor-not-allowed"
                            : "bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800"
                    }`}
            >
                {isRunning ? "游戏进行中…" : "开始游戏 ▶"}
            </button>
        </div>
    );
}
