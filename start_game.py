import asyncio
import platform
import fire
import random

from metagpt.logs import logger
from werewolf_game.werewolf_game import WerewolfGame
from werewolf_game.roles import Moderator, Villager, Werewolf, Seer, Witch, Hunter
from werewolf_game.roles.human_player import prepare_human_player


def init_game_setup(
    player_num=5,
    add_human=False,
    shuffle=True,
    use_reflection=True,
    use_experience=False,
    use_memory_selection=False,
    new_experience_version="",
):
    if player_num == 4:
        roles = [Werewolf, Villager, Villager, Seer]
    elif player_num == 5:
        roles = [Werewolf, Villager, Villager, Seer, Witch]
    elif player_num == 6:
        roles = [Werewolf, Werewolf, Villager, Villager, Seer, Witch]
    elif player_num == 7:
        roles = [Werewolf, Werewolf, Villager, Villager, Hunter, Seer, Witch]
    elif player_num == 8:
        roles = [Werewolf, Werewolf, Villager, Villager, Villager, Hunter, Seer, Witch]
    elif player_num == 9:
        roles = [
            Werewolf,
            Werewolf,
            Werewolf,
            Villager,
            Villager,
            Villager,
            Hunter,
            Seer,
            Witch,
        ]
    elif player_num == 10:
        roles = [
            Werewolf,
            Werewolf,
            Werewolf,
            Villager,
            Villager,
            Villager,
            Guard,
            Hunter,
            Seer,
            Witch,
        ]

    if shuffle:
        # random.seed(100)
        random.shuffle(roles)
    if add_human:
        assigned_role_idx = random.randint(0, len(roles) - 1)
        assigned_role = roles[assigned_role_idx]
        roles[assigned_role_idx] = prepare_human_player(assigned_role)

    players = [
        role(
            name=f"Player{i+1}",
            use_reflection=use_reflection,
            use_experience=use_experience,
            use_memory_selection=use_memory_selection,
            new_experience_version=new_experience_version,
        )
        for i, role in enumerate(roles)
    ]

    if add_human:
        logger.info(
            f"You are assigned {players[assigned_role_idx].name}({players[assigned_role_idx].profile})"
        )

    game_setup = ["Game setup:"] + [
        f"{player.name}: {player.profile}," for player in players
    ]
    game_setup = "\n".join(game_setup)

    return game_setup, players


async def start_game(
    investment: float = 20.0,
    n_round: int = 100,
    player_num: int = 5,
    add_human: bool = False,
    shuffle: bool = True,
    use_reflection: bool = True,
    use_experience: bool = False,
    use_memory_selection: bool = False,
    new_experience_version: str = "",
    # server 模式下由 start_game_endpoint 预先初始化并传入，避免二次随机
    _game_setup: str | None = None,
    _players: list | None = None,
):
    game = WerewolfGame()

    if _game_setup is not None and _players is not None:
        # server 模式：直接使用外部传入的初始化结果
        game_setup = _game_setup
        players = _players
    else:
        # 命令行模式：自行初始化
        game_setup, players = init_game_setup(
            player_num=player_num,
            shuffle=shuffle,
            add_human=add_human,
            use_reflection=use_reflection,
            use_experience=use_experience,
            use_memory_selection=use_memory_selection,
            new_experience_version=new_experience_version,
        )

    players = [Moderator()] + players

    game.hire(players)
    game.invest(investment)
    game.start_project(game_setup)
    await game.run(n_round=n_round)


def main(
    investment: float = 20.0,
    n_round: int = 100,
    player_num: int = 4,  # 玩家人数
    add_human: bool = True,  # 是否将一个角色替换为人类
    shuffle: bool = False,  # 是否打乱身份顺序
    use_reflection: bool = True,  # 是否使用反思
    use_experience: bool = False,  # 是否使用经验
    use_memory_selection: bool = False,
    new_experience_version: str = "",
):

    asyncio.run(
        start_game(
            investment=investment,
            n_round=n_round,
            player_num=player_num,
            add_human=add_human,
            shuffle=shuffle,
            use_reflection=use_reflection,
            use_experience=use_experience,
            use_memory_selection=use_memory_selection,
            new_experience_version=new_experience_version,
        )
    )


if __name__ == "__main__":
    import sys

    _indicator = 1
    if _indicator == 1:
        import uvicorn
        import werewolf_game.server as _srv

        _srv.IS_SERVER_MODE = True
        uvicorn.run("werewolf_game.server:app", host="0.0.0.0", port=8000, reload=False)
    else:
        fire.Fire(main)
