"""
规则奖励函数 —— 贯穿 SFT 数据筛选和 GRPO 强化学习的核心模块。

奖励由两部分组成：
  1. 终局奖励（稀疏）：胜利 +10 / 失败 -5，游戏结束后回溯
  2. 过程奖励（密集）：基于行动意图的即时得分，当步可算

【设计原则】
  过程奖励基于"行动意图"而非"行动结果"：
  - 狼人选择杀预言家 -> 立刻给分，不管女巫是否救人
  - 预言家验出狼人   -> 立刻给分，不管后续是否被投出
  这样过程奖励在 GRPO 在线采样时可以当步评估，
  不依赖游戏结束后的全局状态。

  compute_step_reward 需要的是执行该步时的"当前角色快照"
  （current_roles: dict[玩家名, 角色]），由 Moderator 在每步执行时传入。

使用折扣因子 gamma 从后往前传播，计算每步的累积回报 G_t。
GRPO 阶段还需要组内归一化，计算优势值 advantage。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from werewolf_game.schema import RoleExperience

# --------------------------------------------------------------------------
# 奖励超参数
# --------------------------------------------------------------------------
GAMMA = 0.9  # 折扣因子
WIN_REWARD = 10.0  # 终局胜利奖励
LOSE_REWARD = -5.0  # 终局失败惩罚

# 过程奖励（按角色）
_WEREWOLF_STEP = {
    "target_special": 2.0,  # 选择攻击特殊角色（意图，不管是否成功）
    "vote_out_good": 1.5,  # 投票投出好人（投票结算时可知）
    "vote_out_wolf": -2.0,  # 误投队友
}
_GOOD_STEP = {
    "verify_werewolf": 2.0,  # 预言家验出狼人（Moderator 返回结果时可知）
    "save_used": 1.5,  # 女巫使用解药（使用时立刻可知）
    "vote_out_wolf": 3.0,  # 投票投出狼人（投票结算时可知）
    "vote_out_good": -2.0,  # 误投好人
}

# 特殊角色名称集合
SPECIAL_ROLES = {"Seer", "Witch", "Hunter", "Guard"}


# --------------------------------------------------------------------------
# 辅助函数
# --------------------------------------------------------------------------


def _parse_response_target(response: str) -> str | None:
    """从 response 字符串中提取目标玩家名。

    例如：'Kill Player3' -> 'Player3'
         'Vote Player5' -> 'Player5'
    """
    parts = response.strip().split()
    if len(parts) >= 2:
        return parts[-1]
    return None


# --------------------------------------------------------------------------
# 过程奖励：基于行动意图，当步可算
# --------------------------------------------------------------------------


def compute_step_reward(
    exp: "RoleExperience",
    current_roles: dict[str, str],
) -> float:
    """计算单步即时过程奖励。

    【关键变化】
    参数从 game_result（全局死亡记录）改为 current_roles（当前步骤的角色快照）。
    这样奖励基于"行动意图"，在 GRPO 在线采样时可以当步评估：
    - 狼人选择杀预言家 -> 查 current_roles 确认目标是预言家 -> 立刻给分
    - 不管女巫是否救人，不管预言家最终是否死亡

    Args:
        exp: 当前步骤的经验记录
        current_roles: 执行该步时的角色快照，格式为 {玩家名: 角色}
                       由 Moderator 在每步执行时传入，例如：
                       {"Player1": "Werewolf", "Player3": "Seer", ...}

    Returns:
        float: 即时过程奖励
    """
    reward = 0.0
    profile = exp.profile
    response = exp.response.strip()

    if profile == "Werewolf":
        # 夜晚杀人：目标是特殊角色就给分（意图奖励，不看结果）
        if response.startswith("Kill"):
            target = _parse_response_target(response)
            if target and current_roles.get(target) in SPECIAL_ROLES:
                reward += _WEREWOLF_STEP["target_special"]

        # 白天投票：投出好人加分，误投队友减分
        if response.startswith("Vote") or "vote" in response.lower():
            target = _parse_response_target(response)
            if target:
                target_role = current_roles.get(target, "")
                if target_role and target_role != "Werewolf":
                    reward += _WEREWOLF_STEP["vote_out_good"]
                elif target_role == "Werewolf":
                    reward += _WEREWOLF_STEP["vote_out_wolf"]

    else:  # 好人阵营
        # 预言家验出狼人：Moderator 返回 "werewolf" 时立刻可知
        if profile == "Seer" and "werewolf" in response.lower():
            reward += _GOOD_STEP["verify_werewolf"]

        # 女巫使用解药：Save 动作执行时立刻可知，不管被救者后续是否存活
        if profile == "Witch" and response.strip().lower() == "save":
            reward += _GOOD_STEP["save_used"]

        # 白天投票：投出狼人加分，误投好人减分
        if response.startswith("Vote") or "vote" in response.lower():
            target = _parse_response_target(response)
            if target:
                target_role = current_roles.get(target, "")
                if target_role == "Werewolf":
                    reward += _GOOD_STEP["vote_out_wolf"]
                elif target_role and target_role != "Werewolf":
                    reward += _GOOD_STEP["vote_out_good"]

    return reward


# --------------------------------------------------------------------------
# 累积回报：游戏结束后回溯，折扣传播
# --------------------------------------------------------------------------


def assign_cumulative_rewards(
    experiences: list["RoleExperience"],
    winner: str,
    current_roles_per_step: list[dict[str, str]],
    gamma: float = GAMMA,
) -> list["RoleExperience"]:
    """游戏结束后，为该玩家的所有经验回溯打分。

    使用折扣因子从后往前传播：
        G_t = r_t + gamma * G_{t+1}

    Args:
        experiences: 该玩家本局所有步骤的经验列表（按时间顺序）
        winner: 游戏胜利方，"werewolf" 或 "good guys"
        current_roles_per_step: 每步执行时的角色快照列表，与 experiences 等长。
                                 格式：[{"Player1": "Werewolf", ...}, ...]
        gamma: 折扣因子

    Returns:
        打分后的经验列表（原地修改并返回）
    """
    if not experiences:
        return experiences

    profile = experiences[0].profile
    is_winner = (profile == "Werewolf" and winner == "werewolf") or (
        profile != "Werewolf" and winner == "good guys"
    )
    final_reward = WIN_REWARD if is_winner else LOSE_REWARD

    # 补齐 current_roles_per_step，长度不足时用空字典
    roles_list = list(current_roles_per_step)
    while len(roles_list) < len(experiences):
        roles_list.append({})

    # 从后往前折扣传播
    G = final_reward
    for exp, current_roles in zip(reversed(experiences), reversed(roles_list)):
        step_r = compute_step_reward(exp, current_roles)
        exp.reward = step_r  # type: ignore[attr-defined]
        G = step_r + gamma * G
        exp.cumulative_reward = G  # type: ignore[attr-defined]

    return experiences


# --------------------------------------------------------------------------
# GRPO 优势值：组内归一化
# --------------------------------------------------------------------------


def compute_advantages(
    group_experiences: list["RoleExperience"],
) -> list["RoleExperience"]:
    """对同一局面的一组经验做组内归一化，得到 GRPO 优势值。

    advantage_i = (G_i - mean(G)) / (std(G) + eps)

    在 GRPO 在线采样场景下，G_i 来自 compute_step_reward 的即时过程奖励
    （不含终局奖励），因为终局奖励在采样时尚未结算。

    Args:
        group_experiences: 同一局面下采样的多条经验

    Returns:
        填充了 advantage 字段的经验列表
    """
    if not group_experiences:
        return group_experiences

    rewards = [
        getattr(exp, "cumulative_reward", getattr(exp, "reward", 0.0))
        for exp in group_experiences
    ]
    mean_r = sum(rewards) / len(rewards)
    variance = sum((r - mean_r) ** 2 for r in rewards) / len(rewards)
    std_r = variance**0.5 + 1e-8

    for exp in group_experiences:
        exp.advantage = (getattr(exp, "cumulative_reward", getattr(exp, "reward", 0.0)) - mean_r) / std_r  # type: ignore[attr-defined]

    return group_experiences
