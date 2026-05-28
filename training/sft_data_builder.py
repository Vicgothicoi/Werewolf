"""
SFT 训练集构建器。

从 data_collector 产出的原始 JSONL 文件中，
用规则奖励函数的打分结果筛选高质量样本，
构造 "当前局面 + 推理过程 + 决策回复" 格式的训练集。

输出格式（OpenAI / LLaMA-Factory 通用）：
    {
        "messages": [
            {"role": "system",    "content": "..."},
            {"role": "user",      "content": "..."},
            {"role": "assistant", "content": "<think>...</think>\n..."}
        ]
    }

用法：
    python -m training.sft_data_builder \
        --input_dir training/data/raw \
        --output_path training/data/sft.jsonl \
        --reward_threshold 2.0
"""

from __future__ import annotations

import json
from pathlib import Path

import fire

from metagpt.logs import logger


# ── Prompt 模板 ─────────────────────────────────────────────────────────────

SYSTEM_TEMPLATE = """你是狼人杀游戏中的{profile}角色，请根据当前局势做出最优决策。
游戏规则：狼人阵营需要消灭所有好人；好人阵营需要找出并投票淘汰所有狼人。
请先在 <think> 标签内进行推理，再给出最终决策。"""

USER_TEMPLATE = """游戏配置：
{game_setup}

当前局势（客观事实）：
{hard_facts}

行为观测（发言与倾向）：
{soft_signals}

主持人指令：
{instruction}"""

ASSISTANT_TEMPLATE = """<think>
{reflection}
</think>

{response}"""


# ── 样本构造 ────────────────────────────────────────────────────────────────


def build_sample(record: dict) -> dict:
    """将单条经验记录转换为训练样本。"""
    system = SYSTEM_TEMPLATE.format(profile=record["profile"])
    user = USER_TEMPLATE.format(
        game_setup=record.get("game_setup", "")
        .replace("0 | Game setup:\n", "")
        .strip(),
        hard_facts=record.get("hard_facts", ""),
        soft_signals=record.get("soft_signals", ""),
        instruction=record.get("instruction", ""),
    )
    assistant = ASSISTANT_TEMPLATE.format(
        reflection=record.get("reflection", ""),
        response=record.get("response", ""),
    )
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


# ── 主构建逻辑 ───────────────────────────────────────────────────────────────


def build_sft_dataset(
    input_dir: str = "training/data/raw",
    output_path: str = "training/data/sft.jsonl",
    reward_threshold: float = 2.0,
    min_reflection_len: int = 10,
    roles: list[str] | None = None,
):
    """从原始经验数据中筛选高质量样本，构建 SFT 训练集。

    Args:
        input_dir: data_collector 输出的原始 JSONL 目录
        output_path: SFT 训练集输出路径
        reward_threshold: cumulative_reward 筛选阈值，高于此值才纳入训练集
        min_reflection_len: reflection 最短字符数，过滤空反思
        roles: 只保留指定角色的样本，None 表示保留全部角色
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    all_files = list(input_path.glob("**/*.jsonl"))
    if not all_files:
        raise FileNotFoundError(f"在 {input_dir} 下未找到任何 .jsonl 文件")

    logger.info(f"[sft_builder] 找到 {len(all_files)} 个文件，开始筛选...")

    total_read = 0
    total_kept = 0
    role_stats: dict[str, int] = {}

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as out_f:
        for file_path in all_files:
            with open(file_path, "r", encoding="utf-8") as in_f:
                for line in in_f:
                    line = line.strip()
                    if not line:
                        continue
                    total_read += 1

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 过滤1：角色白名单
                    if roles and record.get("profile") not in roles:
                        continue

                    # 过滤2：奖励阈值
                    if record.get("cumulative_reward", 0.0) < reward_threshold:
                        continue

                    # 过滤3：reflection 质量
                    reflection = record.get("reflection", "")
                    if len(reflection) < min_reflection_len:
                        continue

                    # 过滤4：response 不能为空
                    if not record.get("response", "").strip():
                        continue

                    sample = build_sample(record)
                    out_f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    total_kept += 1

                    profile = record.get("profile", "Unknown")
                    role_stats[profile] = role_stats.get(profile, 0) + 1

    logger.info(
        f"[sft_builder] 完成：读取 {total_read} 条，保留 {total_kept} 条"
        f"（筛选率 {total_kept/max(total_read,1)*100:.1f}%）"
    )
    logger.info(f"[sft_builder] 角色分布：{role_stats}")
    logger.info(f"[sft_builder] 训练集已保存至 {output_path}")

    return total_kept


def main(
    input_dir: str = "training/data/raw",
    output_path: str = "training/data/sft.jsonl",
    reward_threshold: float = 2.0,
    min_reflection_len: int = 10,
):
    build_sft_dataset(
        input_dir=input_dir,
        output_path=output_path,
        reward_threshold=reward_threshold,
        min_reflection_len=min_reflection_len,
    )


if __name__ == "__main__":
    fire.Fire(main)
