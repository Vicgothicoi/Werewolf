// 与 server.py broadcast() 序列化的字段一一对应
export interface GameMessage {
    sent_from: string;   // 发言者名字，例如 "Player3"
    role: string;        // 角色身份，例如 "Werewolf"
    content: string;     // 消息内容，带时间戳前缀，例如 "2 | Kill Player2"
    restricted_to: string; // 私密消息接收方，公开消息为空字符串 ""
}
