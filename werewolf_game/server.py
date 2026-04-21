import asyncio
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from metagpt.schema import Message

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 已连接的 WebSocket 客户端列表
_clients: list[WebSocket] = []


def broadcast(message: Message):
    """同步接口，供 publish_message 调用。
    将消息序列化后推送给所有已连接的前端客户端。
    """
    data = json.dumps(
        {
            "sent_from": message.sent_from,
            "role": message.role,
            "content": message.content,
            "restricted_to": message.restricted_to,
        },
        ensure_ascii=False,
    )
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_broadcast_async(data))
    except RuntimeError:
        pass  # 没有运行中的事件循环时静默跳过


async def _broadcast_async(data: str):
    """异步广播，逐一发送给所有客户端，断开的客户端自动移除。"""
    for ws in _clients.copy():
        try:
            await ws.send_text(data)
        except Exception:
            _clients.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    try:
        while True:
            # 保持连接存活，忽略客户端发来的消息
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in _clients:
            _clients.remove(ws)


@app.post("/game/start")
async def start_game_endpoint(
    player_num: int = 5,
    shuffle: bool = True,
    use_reflection: bool = True,
    use_experience: bool = False,
):
    """启动一局游戏，游戏消息会通过 /ws 实时推送。"""
    from start_game import start_game

    asyncio.create_task(
        start_game(
            player_num=player_num,
            shuffle=shuffle,
            use_reflection=use_reflection,
            use_experience=use_experience,
        )
    )
    return {"status": "started"}
