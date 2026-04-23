import asyncio
import json
import uuid
from datetime import datetime

import redis.asyncio as aioredis
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

# ── WebSocket 客户端 ──────────────────────────────────────────────
_clients: list[WebSocket] = []

# ── 运行模式 ──────────────────────────────────────────────────────
IS_SERVER_MODE: bool = False

# ── 人类玩家 ──────────────────────────────────────────────────────
_human_profile: str | None = None
_human_input_future: asyncio.Future | None = None

# ── Redis ─────────────────────────────────────────────────────────
_redis: aioredis.Redis | None = None
_current_game_id: str | None = None  # 当前局的 game_id
_current_game_meta: dict = {}  # 当前局的 meta 信息（胜负、人数等）

REDIS_URL = "redis://localhost:6379"
GAME_INDEX_KEY = "werewolf:game_index"  # List，按时间顺序存所有 game_id


@app.on_event("startup")
async def startup():
    global _redis
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)


@app.on_event("shutdown")
async def shutdown():
    if _redis:
        await _redis.aclose()


# ── 工具函数 ──────────────────────────────────────────────────────


def _game_messages_key(game_id: str) -> str:
    return f"werewolf:game:{game_id}:messages"


def _game_meta_key(game_id: str) -> str:
    return f"werewolf:game:{game_id}:meta"


def set_human_profile(profile: str | None):
    global _human_profile
    _human_profile = profile


def _init_game_id(player_num: int, add_human: bool):
    """新局开始时生成 game_id 并初始化 meta。"""
    global _current_game_id, _current_game_meta
    _current_game_id = uuid.uuid4().hex[:8]
    _current_game_meta = {
        "game_id": _current_game_id,
        "player_num": player_num,
        "add_human": str(add_human),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "winner": "",
        "win_reason": "",
    }


# ── 广播函数 ──────────────────────────────────────────────────────


def broadcast(message: Message):
    """
    有人类玩家时过滤不属于该玩家的加密消息；无人类玩家时推送所有消息。
    同时把消息追加到 Redis 当前局的消息列表。
    """
    if message.restricted_to and _human_profile is not None:
        if _human_profile not in message.restricted_to:
            return

    payload = {
        "sent_from": message.sent_from,
        "role": message.role,
        "content": message.content,
        "restricted_to": message.restricted_to,
    }
    data = json.dumps(payload, ensure_ascii=False)

    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_broadcast_async(data))
        # 追加到 Redis（无论是否有人类玩家都存，保留完整记录）
        if _redis and _current_game_id:
            full_payload = {
                "sent_from": message.sent_from,
                "role": message.role,
                "content": message.content,
                "restricted_to": message.restricted_to,
            }
            loop.create_task(
                _redis.rpush(
                    _game_messages_key(_current_game_id),
                    json.dumps(full_payload, ensure_ascii=False),
                )
            )
    except RuntimeError:
        pass


def broadcast_game_over():
    """通知前端游戏结束，并把对局 meta 写入 Redis。"""
    data = json.dumps({"type": "game_over"}, ensure_ascii=False)
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_broadcast_async(data))
        if _redis and _current_game_id:
            loop.create_task(_save_game_meta())
    except RuntimeError:
        pass


async def _save_game_meta():
    """把当前局 meta 写入 Redis，并追加到全局索引。"""
    if not _redis or not _current_game_id:
        return
    # 逐字段写入，兼容旧版 Redis
    for field, value in _current_game_meta.items():
        await _redis.hset(_game_meta_key(_current_game_id), field, value)
    await _redis.rpush(GAME_INDEX_KEY, _current_game_id)


def update_game_result(winner: str, win_reason: str):
    """由 moderator 在游戏结束时调用，更新胜负信息。"""
    _current_game_meta["winner"] = winner
    _current_game_meta["win_reason"] = win_reason


def broadcast_await_input(instruction: str):
    data = json.dumps(
        {"type": "await_input", "instruction": instruction}, ensure_ascii=False
    )
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_broadcast_async(data))
    except RuntimeError:
        pass


async def wait_for_human_input(instruction: str) -> str:
    global _human_input_future
    from metagpt.logs import logger

    loop = asyncio.get_event_loop()
    _human_input_future = loop.create_future()
    logger.info(
        f"[Server] wait_for_human_input: _clients={len(_clients)}, broadcasting await_input"
    )
    await _broadcast_async(
        json.dumps(
            {"type": "await_input", "instruction": instruction}, ensure_ascii=False
        )
    )
    logger.info(f"[Server] await_input broadcast done, waiting for future...")
    try:
        rsp = await _human_input_future
        logger.info(f"[Server] future resolved: {rsp!r}")
    finally:
        _human_input_future = None
    return rsp


async def broadcast_player_info(name: str, profile: str):
    await _broadcast_async(
        json.dumps(
            {"type": "player_info", "name": name, "profile": profile},
            ensure_ascii=False,
        )
    )


async def _broadcast_async(data: str):
    for ws in _clients.copy():
        try:
            await ws.send_text(data)
        except Exception:
            _clients.remove(ws)


# ── WebSocket 端点 ────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    try:
        while True:
            text = await ws.receive_text()
            if _human_input_future is not None and not _human_input_future.done():
                _human_input_future.set_result(text)
    except WebSocketDisconnect:
        if ws in _clients:
            _clients.remove(ws)


# ── HTTP 端点 ─────────────────────────────────────────────────────


@app.post("/game/start")
async def start_game_endpoint(
    player_num: int = 5,
    shuffle: bool = True,
    use_reflection: bool = True,
    use_experience: bool = False,
    add_human: bool = False,
):
    from start_game import start_game, init_game_setup
    from werewolf_game.roles.human_player import HumanPlayerMixin

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
    _init_game_id(player_num=player_num, add_human=add_human)

    if human_player:
        await broadcast_player_info(human_player.name, human_player.profile)

    asyncio.create_task(
        start_game(
            investment=20.0, n_round=100, _game_setup=game_setup, _players=players
        )
    )
    return {"status": "started", "game_id": _current_game_id}


@app.get("/games")
async def list_games():
    """返回历史对局列表（最新的在前）。"""
    if not _redis:
        return []
    game_ids = await _redis.lrange(GAME_INDEX_KEY, 0, -1)
    game_ids = list(reversed(game_ids))  # 最新的在前
    result = []
    for gid in game_ids:
        meta = await _redis.hgetall(_game_meta_key(gid))
        if meta:
            result.append(meta)
    return result


@app.get("/games/{game_id}")
async def get_game(game_id: str):
    """返回指定对局的所有消息。"""
    if not _redis:
        return []
    raw_messages = await _redis.lrange(_game_messages_key(game_id), 0, -1)
    return [json.loads(m) for m in raw_messages]
