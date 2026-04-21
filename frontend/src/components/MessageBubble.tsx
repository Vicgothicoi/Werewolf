import { useState } from "react";
import type { GameMessage } from "../types";

// 角色 → 阵营
const WEREWOLF_ROLES = ["Werewolf"];
const SPECIAL_ROLES = ["Seer", "Witch", "Hunter", "Guard"];
const MODERATOR_ROLES = ["Moderator", "User"];

// 角色名 → 图片路径（放在 public/avatars/ 下）
const AVATAR_MAP: Record<string, string> = {
    Werewolf: "/avatars/werewolf.jpg",
    Villager: "/avatars/villager.jpg",
    Seer: "/avatars/seer.jpg",
    Witch: "/avatars/witch.jpg",
    Hunter: "/avatars/hunter.jpg",
    Guard: "/avatars/guard.jpg",
    Moderator: "/avatars/moderator.jpg",
    User: "/avatars/moderator.jpg",
};

function getRoleStyle(role: string): {
    border: string;
    badge: string;
    avatar: string;
} {
    if (MODERATOR_ROLES.includes(role)) {
        return {
            border: "border-gray-400",
            badge: "bg-gray-200 text-gray-700",
            avatar: "bg-gray-500",
        };
    }
    if (WEREWOLF_ROLES.includes(role)) {
        return {
            border: "border-red-400",
            badge: "bg-red-100 text-red-700",
            avatar: "bg-red-500",
        };
    }
    if (SPECIAL_ROLES.includes(role)) {
        return {
            border: "border-blue-400",
            badge: "bg-blue-100 text-blue-700",
            avatar: "bg-blue-500",
        };
    }
    // 村民
    return {
        border: "border-green-400",
        badge: "bg-green-100 text-green-700",
        avatar: "bg-green-500",
    };
}

// 去掉消息内容开头的时间戳前缀，例如 "3 | 天黑了" → "天黑了"
function stripTimestamp(content: string): string {
    return content.replace(/^\d+\s*\|\s*/, "");
}

// 从 sent_from 取首字母作为头像文字，例如 "Player3" → "P3"
function getAvatarLabel(sentFrom: string): string {
    const match = sentFrom.match(/^([A-Za-z]+)(\d*)$/);
    if (!match) return sentFrom.slice(0, 2).toUpperCase();
    const letters = match[1].slice(0, 1).toUpperCase();
    const digits = match[2].slice(0, 2);
    return letters + digits;
}

interface Props {
    message: GameMessage;
    isTyping?: boolean;
}

export default function MessageBubble({ message, isTyping = false }: Props) {
    const { sent_from, role, content, restricted_to } = message;
    const isPrivate = restricted_to !== "";
    const style = getRoleStyle(role);
    const displayContent = stripTimestamp(content);
    const avatarLabel = getAvatarLabel(sent_from || role);
    const avatarSrc = AVATAR_MAP[role];

    // 图片加载失败时回退到纯色文字头像
    const [imgFailed, setImgFailed] = useState(false);

    return (
        <div className={`flex gap-3 py-2 ${isPrivate ? "opacity-75" : ""}`}>
            {/* 头像：优先显示角色图片，失败时回退到纯色缩写 */}
            {avatarSrc && !imgFailed ? (
                <img
                    src={avatarSrc}
                    alt={role}
                    className="flex-shrink-0 w-9 h-9 rounded-full object-cover"
                    onError={() => setImgFailed(true)}
                />
            ) : (
                <div
                    className={`flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-bold ${style.avatar}`}
                >
                    {avatarLabel}
                </div>
            )}

            {/* 消息主体 */}
            <div className="flex-1 min-w-0">
                {/* 发言者信息行 */}
                <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-sm text-gray-900">
                        {sent_from || role}
                    </span>
                    <span
                        className={`text-xs px-1.5 py-0.5 rounded font-medium ${style.badge}`}
                    >
                        {role}
                    </span>
                    {isPrivate && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700 font-medium">
                            🔒 私密
                        </span>
                    )}
                </div>

                {/* 消息内容气泡 */}
                <div
                    className={`inline-block max-w-full px-3 py-2 rounded-2xl rounded-tl-sm text-sm text-gray-800 bg-white border ${style.border} shadow-sm whitespace-pre-wrap break-words`}
                >
                    {displayContent}
                    {isTyping && (
                        <span className="inline-block w-0.5 h-3.5 bg-gray-500 ml-0.5 align-middle animate-pulse" />
                    )}
                </div>
            </div>
        </div>
    );
}
