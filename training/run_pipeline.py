"""
完整训练流水线入口。

执行顺序：
  Step 1: 自我博弈收集原始经验数据（data_collector）
  Step 2: 用规则奖励函数筛选，构建 SFT 训练集（sft_data_builder）
  Step 3: 监督微调（sft_trainer）
  Step 4: GRPO 强化学习（grpo_trainer）
  Step 5: （可选）用新模型继续自我博弈，形成迭代闭环

用法：
    # 完整流程
    python -m training.run_pipeline --steps all

    # 只跑数据收集 + SFT
    python -m training.run_pipeline --steps collect,sft

    # 只跑 GRPO（已有 SFT checkpoint）
    python -m training.run_pipeline --steps grpo

    # 查看各步骤参数
    python -m training.run_pipeline --help
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import fire

from metagpt.logs import logger


# ── 各步骤入口 ───────────────────────────────────────────────────────────────


def step_collect(
    n_games: int = 50,
    player_num: int = 6,
    use_reflection: bool = True,
    output_dir: str = "training/data/raw",
):
    """Step 1: 自我博弈，收集带奖励分数的原始经验数据。"""
    from training.data_collector import collect

    logger.info("=" * 60)
    logger.info("Step 1: 自我博弈数据收集")
    logger.info("=" * 60)
    asyncio.run(
        collect(
            n_games=n_games,
            player_num=player_num,
            use_reflection=use_reflection,
            output_dir=output_dir,
        )
    )


def step_build_sft(
    input_dir: str = "training/data/raw",
    output_path: str = "training/data/sft.jsonl",
    reward_threshold: float = 2.0,
):
    """Step 2: 筛选高奖励经验，构建 SFT 训练集。"""
    from training.sft_data_builder import build_sft_dataset

    logger.info("=" * 60)
    logger.info("Step 2: 构建 SFT 训练集")
    logger.info("=" * 60)
    n = build_sft_dataset(
        input_dir=input_dir,
        output_path=output_path,
        reward_threshold=reward_threshold,
    )
    logger.info(f"SFT 训练集共 {n} 条样本")


def step_sft(
    data_path: str = "training/data/sft.jsonl",
    output_dir: str = "training/data/checkpoints/sft",
    model_name: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    num_epochs: int = 3,
):
    """Step 3: 监督微调（SFT）。"""
    from training.sft_trainer import train

    logger.info("=" * 60)
    logger.info("Step 3: 监督微调（SFT）")
    logger.info("=" * 60)
    train(
        data_path=data_path,
        output_dir=output_dir,
        model_name=model_name,
        num_epochs=num_epochs,
    )


def step_grpo(
    sft_checkpoint: str = "training/data/checkpoints/sft",
    data_path: str = "training/data/raw",
    output_dir: str = "training/data/checkpoints/grpo",
    base_model: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    num_epochs: int = 1,
):
    """Step 4: GRPO 强化学习。"""
    from training.grpo_trainer import train

    logger.info("=" * 60)
    logger.info("Step 4: GRPO 强化学习")
    logger.info("=" * 60)
    train(
        sft_checkpoint=sft_checkpoint,
        data_path=data_path,
        output_dir=output_dir,
        base_model=base_model,
        num_epochs=num_epochs,
    )


# ── 主入口 ───────────────────────────────────────────────────────────────────

STEP_MAP = {
    "collect": step_collect,
    "build_sft": step_build_sft,
    "sft": step_sft,
    "grpo": step_grpo,
}

ALL_STEPS = ["collect", "build_sft", "sft", "grpo"]


def run(
    steps: str = "all",
    # collect 参数
    n_games: int = 50,
    player_num: int = 6,
    # sft_data_builder 参数
    reward_threshold: float = 2.0,
    # 模型参数
    model_name: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    sft_epochs: int = 3,
    grpo_epochs: int = 1,
    # 路径参数
    raw_data_dir: str = "training/data/raw",
    sft_data_path: str = "training/data/sft.jsonl",
    sft_checkpoint: str = "training/data/checkpoints/sft",
    grpo_checkpoint: str = "training/data/checkpoints/grpo",
):
    """运行完整或部分训练流水线。

    Args:
        steps: 要执行的步骤，逗号分隔，或 "all"。
               可选值：collect, build_sft, sft, grpo
               示例：--steps collect,build_sft,sft
        n_games: 自我博弈局数
        player_num: 每局玩家数量
        reward_threshold: SFT 筛选奖励阈值
        model_name: 基础模型名称或本地路径
        sft_epochs: SFT 训练轮数
        grpo_epochs: GRPO 训练轮数
        raw_data_dir: 原始数据目录
        sft_data_path: SFT 训练集路径
        sft_checkpoint: SFT checkpoint 保存路径
        grpo_checkpoint: GRPO checkpoint 保存路径
    """
    # 解析步骤列表
    if steps.strip().lower() == "all":
        step_list = ALL_STEPS
    else:
        step_list = [s.strip() for s in steps.split(",")]

    invalid = [s for s in step_list if s not in STEP_MAP]
    if invalid:
        raise ValueError(f"未知步骤：{invalid}，可选：{list(STEP_MAP.keys())}")

    logger.info(f"[pipeline] 将执行步骤：{step_list}")
    start_time = time.time()

    for step_name in step_list:
        step_start = time.time()

        if step_name == "collect":
            step_collect(
                n_games=n_games,
                player_num=player_num,
                output_dir=raw_data_dir,
            )
        elif step_name == "build_sft":
            step_build_sft(
                input_dir=raw_data_dir,
                output_path=sft_data_path,
                reward_threshold=reward_threshold,
            )
        elif step_name == "sft":
            step_sft(
                data_path=sft_data_path,
                output_dir=sft_checkpoint,
                model_name=model_name,
                num_epochs=sft_epochs,
            )
        elif step_name == "grpo":
            step_grpo(
                sft_checkpoint=sft_checkpoint,
                data_path=raw_data_dir,
                output_dir=grpo_checkpoint,
                base_model=model_name,
                num_epochs=grpo_epochs,
            )

        elapsed = time.time() - step_start
        logger.info(f"[pipeline] {step_name} 完成，耗时 {elapsed:.1f}s")

    total = time.time() - start_time
    logger.info(f"[pipeline] 全部步骤完成，总耗时 {total:.1f}s")


if __name__ == "__main__":
    fire.Fire(run)
