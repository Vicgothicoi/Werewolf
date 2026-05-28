"""
自我博弈数据收集器。

流程：
  1. 循环调用 start_game() 运行多局游戏
  2. 每局结束后从 Moderator 获取胜负结果
  3. 调用 assign_cumulative_rewards() 为每个玩家的经验打分
  4. 将带奖励分数的经验持久化到 ChromaDB 和本地 JSON

用法：
    python -m training.data_collector --n_games 50 --player_num 6
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import fire

from metagpt.const import WORKSPACE_ROOT
from metagpt.logs import logger
from start_game import init_game_setup, start_game
from werewolf_game.roles import Moderator
from werewolf_game.werewolf_game import WerewolfGame
from training.reward_function import assign_cumulative_rewards


# ── 单局游戏运行 ────────────────────────────────────────────────────────────


async def run_single_game(
    player_num: int = 6,
    use_reflection: bool = True,
    use_experience: bool = False,
    n_round: int = 100,
) -> dict:
    """运行一局游戏，返回包含经验和结果的字典。

    Returns:
        {
            "winner": str,
            "game_setup": str,
            "round_id": str,
            "dead_players": dict[str, str],   # {玩家名: 角色}
            "vote_results": list,
            "player_experiences": dict[str, list[RoleExperience]],
        }
    """
    game_setup, players = init_game_setup(
        player_num=player_num,
        shuffle=True,
        use_reflection=use_reflection,
        use_experience=use_experience,
    )

    game = WerewolfGame()
    moderator = Moderator()
    all_players = [moderator] + players
    game.hire(all_players)
    game.invest(20.0)
    game.start_project(game_setup)
    await game.run(n_round=n_round)

    # 从 Moderator 提取游戏结果
    winner = moderator.winner or "unknown"
    round_id = str(uuid.uuid4())[:8]

    # 构建死亡记录：{玩家名: 角色}，用于过程奖励计算
    dead_players: dict[str, str] = {}
    roles_in_env = game.environment.get_roles()
    for role_setting, role in roles_in_env.items():
        if hasattr(role, "status") and role.status == 1:
            dead_players[role.name] = role.profile

    game_result = {
        "winner": winner,
        "dead_players": dead_players,
        "vote_results": [],  # 当前版本暂不追踪详细投票记录
    }

    # 收集各玩家经验
    player_experiences: dict[str, list] = {}
    for role_setting, role in roles_in_env.items():
        if hasattr(role, "experiences") and role.experiences:
            player_experiences[role.name] = role.experiences

    return {
        "winner": winner,
        "game_setup": game_setup,
        "round_id": round_id,
        "game_result": game_result,
        "player_experiences": player_experiences,
    }


# ── 奖励打分与持久化 ────────────────────────────────────────────────────────


def score_and_save(game_data: dict, output_dir: Path) -> int:
    """对本局经验打分并保存到本地 JSONL 文件。

    Args:
        game_data: run_single_game() 的返回值
        output_dir: 保存目录

    Returns:
        本局保存的经验条数
    """
    winner = game_data["winner"]
    game_setup = game_data["game_setup"]
    round_id = game_data["round_id"]
    game_result = game_data["game_result"]
    player_experiences = game_data["player_experiences"]

    output_dir.mkdir(parents=True, exist_ok=True)
    save_path = output_dir / f"game_{round_id}.jsonl"

    total = 0
    with open(save_path, "w", encoding="utf-8") as f:
        for player_name, experiences in player_experiences.items():
            # 补充 round_id / outcome / game_setup
            outcome = (
                "won"
                if (
                    (experiences[0].profile == "Werewolf" and winner == "werewolf")
                    or (experiences[0].profile != "Werewolf" and winner == "good guys")
                )
                else "lost"
            )
            for exp in experiences:
                exp.round_id = round_id
                exp.outcome = outcome
                exp.game_setup = game_setup

            # 奖励打分
            scored = assign_cumulative_rewards(experiences, winner, game_result)

            for exp in scored:
                record = exp.dict()
                # reward / cumulative_reward / advantage 是动态属性，手动补充
                record["reward"] = getattr(exp, "reward", 0.0)
                record["cumulative_reward"] = getattr(exp, "cumulative_reward", 0.0)
                record["advantage"] = getattr(exp, "advantage", 0.0)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                total += 1

    logger.info(
        f"[data_collector] game {round_id} saved {total} experiences → {save_path}"
    )
    return total


# ── 主入口 ──────────────────────────────────────────────────────────────────


async def collect(
    n_games: int = 50,
    player_num: int = 6,
    use_reflection: bool = True,
    use_experience: bool = False,
    n_round: int = 100,
    output_dir: str = "training/data/raw",
):
    """运行 n_games 局自我博弈，收集带奖励分数的经验数据。

    Args:
        n_games: 自我博弈局数
        player_num: 每局玩家数量（4-9）
        use_reflection: 是否启用反思机制
        use_experience: 是否启用经验检索（冷启动阶段建议关闭）
        n_round: 每局最大轮数
        output_dir: 原始数据保存目录
    """
    out = Path(output_dir)
    total_exp = 0

    for i in range(n_games):
        logger.info(f"[data_collector] ── 第 {i+1}/{n_games} 局 ──")
        try:
            game_data = await run_single_game(
                player_num=player_num,
                use_reflection=use_reflection,
                use_experience=use_experience,
                n_round=n_round,
            )
            cnt = score_and_save(game_data, out)
            total_exp += cnt
            logger.info(
                f"[data_collector] 胜者: {game_data['winner']} | 累计经验: {total_exp}"
            )
        except Exception as e:
            logger.error(f"[data_collector] 第 {i+1} 局出错，跳过: {e}")
            continue

    logger.info(f"[data_collector] 完成！共收集 {total_exp} 条经验，保存至 {out}")


def main(
    n_games: int = 50,
    player_num: int = 6,
    use_reflection: bool = True,
    use_experience: bool = False,
    n_round: int = 100,
    output_dir: str = "training/data/raw",
):
    asyncio.run(
        collect(
            n_games=n_games,
            player_num=player_num,
            use_reflection=use_reflection,
            use_experience=use_experience,
            n_round=n_round,
            output_dir=output_dir,
        )
    )


if __name__ == "__main__":
    fire.Fire(main)
