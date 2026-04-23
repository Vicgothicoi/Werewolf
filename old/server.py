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

# server 模式标志：由 uvicorn 启动时置为 True，命令行模式保持 False
IS_SERVER_MODE: bool = False

# 当前局的人类玩家 profile（如 "Seer"），None 表示无人类玩家
_human_profile: str | None = None

# 等待人类玩家输入的 Future，None 表示当前不在等待
_human_input_future: asyncio.Future | None = None


def set_human_profile(profile: str | None):
    """游戏开始时由 start_game 调用，记录人类玩家的 profile。"""
    global _human_profile
    _human_profile = profile


def broadcast(message: Message):
    """同步接口，供 publish_message 调用。
    有人类玩家时过滤不属于该玩家的加密消息；无人类玩家时推送所有消息。
    """
    if message.restricted_to and _human_profile is not None:
        if _human_profile not in message.restricted_to:
            return

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


def broadcast_game_over():
    """游戏结束时推送特殊事件，通知前端重置状态。"""
    data = json.dumps({"type": "game_over"}, ensure_ascii=False)
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_broadcast_async(data))
    except RuntimeError:
        pass


def broadcast_await_input(instruction: str):
    """通知前端当前需要人类玩家输入。"""
    data = json.dumps(
        {"type": "await_input", "instruction": instruction},
        ensure_ascii=False,
    )
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_broadcast_async(data))
    except RuntimeError:
        pass


async def wait_for_human_input(instruction: str) -> str:
    """挂起当前协程，等待前端通过 WebSocket 发来人类玩家的输入。"""
    global _human_input_future
    loop = asyncio.get_event_loop()
    _human_input_future = loop.create_future()
    # 直接 await 广播，确保前端收到 await_input 事件后再挂起等待输入
    await _broadcast_async(
        json.dumps(
            {"type": "await_input", "instruction": instruction},
            ensure_ascii=False,
        )
    )
    try:
        rsp = await _human_input_future
    finally:
        _human_input_future = None
    return rsp


async def broadcast_player_info(name: str, profile: str):
    """游戏开始时通知前端人类玩家的身份。"""
    await _broadcast_async(
        json.dumps(
            {"type": "player_info", "name": name, "profile": profile},
            ensure_ascii=False,
        )
    )


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
            text = await ws.receive_text()
            # 若当前正在等待人类输入，将收到的文本 resolve 给 Future
            if _human_input_future is not None and not _human_input_future.done():
                _human_input_future.set_result(text)
    except WebSocketDisconnect:
        if ws in _clients:
            _clients.remove(ws)


@app.post("/game/start")
async def start_game_endpoint(
    player_num: int = 5,
    shuffle: bool = True,
    use_reflection: bool = True,
    use_experience: bool = False,
    add_human: bool = False,
):
    """启动一局游戏，游戏消息会通过 /ws 实时推送。"""
    from start_game import start_game, init_game_setup
    from werewolf_game.roles.human_player import HumanPlayerMixin

    # 只调用一次 init_game_setup，结果同时用于 player_info 推送和游戏启动
    game_setup, players = init_game_setup(
        player_num=player_num,
        shuffle=shuffle,
        add_human=add_human,
        use_reflection=use_reflection,
        use_experience=use_experience,
    )

    human_player = None
    if add_human:
        for p in players:
            if isinstance(p, HumanPlayerMixin):
                human_player = p
                break

    set_human_profile(human_player.profile if human_player else None)

    # 在返回响应之前推送 player_info，确保前端收到后才执行 setHumanRole(null)
    if human_player:
        await broadcast_player_info(human_player.name, human_player.profile)

    # 把已初始化的 game_setup 和 players 直接传给 start_game，不再二次随机
    asyncio.create_task(
        start_game(
            investment=20.0,
            n_round=100,
            _game_setup=game_setup,
            _players=players,
        )
    )
    return {"status": "started"}
