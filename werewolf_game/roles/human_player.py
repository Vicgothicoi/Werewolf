import asyncio

from werewolf_game.actions import Speak
from werewolf_game.roles import BasePlayer
from metagpt.schema import Message
from metagpt.logs import logger


class HumanPlayerMixin:
    """标记类，用于在 start_game 中识别人类玩家实例。"""

    pass


async def _act(self):
    todo = self._rc.todo
    memories = self.get_all_memories()

    input_instruction = (
        f"## You are {self.name}({self.profile})\n"
        f"## Guidance:\n"
        f"1. If you are performing a special action or exercising a vote,\n"
        f"   end your response with 'PlayerX', replace PlayerX with the actual player name,\n"
        f"   e.g., '..., kill/hunt/poison/verify/.../vote Player1'.\n"
        f"2. If it is a daytime free speech, you can speak in whatever format.\n"
        f"Now, please speak: "
    )

    # 根据运行模式选择输入方式
    try:
        import werewolf_game.server as _srv

        is_server = _srv.IS_SERVER_MODE
    except Exception:
        is_server = False

    if is_server:
        # server 模式：通过 WebSocket 等待前端输入
        from werewolf_game.server import wait_for_human_input

        rsp = await wait_for_human_input(input_instruction)
    else:
        # 命令行模式：阻塞等待终端输入
        rsp = input(input_instruction)

    msg_cause_by = type(todo)
    msg_restricted_to = "" if isinstance(todo, Speak) else f"Moderator,{self.profile}"

    msg = Message(
        content=rsp,
        role=self.profile,
        sent_from=self.name,
        cause_by=msg_cause_by,
        send_to="",
        restricted_to=msg_restricted_to,
    )

    logger.info(f"{self._setting}: {rsp}")
    return msg


def prepare_human_player(player_class: BasePlayer):
    """动态创建继承自指定角色类的人类玩家类，同时混入 HumanPlayerMixin 便于识别。"""
    HumanPlayer = type(
        "HumanPlayer",
        (HumanPlayerMixin, player_class),
        {"_act": _act},
    )
    return HumanPlayer
