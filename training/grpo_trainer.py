"""
GRPO 强化学习训练脚本。

在 SFT checkpoint 基础上，使用与 sft_data_builder 相同的规则奖励函数
驱动 GRPO 策略梯度优化。

核心设计：
  - Actor 和 Reference 共享同一份底座权重，Reference 禁用 LoRA
  - 对每个局面采样 G 个候选回复，组内归一化得到优势值
  - 奖励函数与 SFT 筛选阶段完全一致，保证优化目标对齐

依赖：
    pip install transformers peft trl bitsandbytes accelerate

用法：
    python -m training.grpo_trainer \
        --sft_checkpoint training/data/checkpoints/sft \
        --data_path training/data/raw \
        --output_dir training/data/checkpoints/grpo
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import fire
import torch
from datasets import Dataset
from peft import (
    PeftModel,
    LoraConfig,
    TaskType,
    get_peft_model,
    prepare_model_for_kbit_training,
)
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)
from trl import GRPOConfig, GRPOTrainer

from metagpt.logs import logger
from training.reward_function import (
    assign_cumulative_rewards,
    compute_advantages,
    WIN_REWARD,
    LOSE_REWARD,
)
from training.sft_data_builder import USER_TEMPLATE, SYSTEM_TEMPLATE


# ── 默认超参数 ───────────────────────────────────────────────────────────────

DEFAULT_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
GROUP_SIZE = 4  # 每个局面采样的候选回复数 G
MAX_NEW_TOKENS = 512
MAX_SEQ_LENGTH = 2048


# ── 数据加载 ─────────────────────────────────────────────────────────────────


def load_grpo_prompts(data_dir: str, max_samples: int = 2000) -> Dataset:
    """从原始经验数据中提取局面 prompt，用于 GRPO 采样。

    每条样本只保留 prompt（system + user），不包含 assistant 回复，
    让模型自由生成候选回复后再用奖励函数打分。

    Args:
        data_dir: data_collector 输出的原始 JSONL 目录
        max_samples: 最大样本数（避免数据集过大）

    Returns:
        包含 "prompt" 和 "metadata" 字段的 Dataset
    """
    data_path = Path(data_dir)
    all_files = list(data_path.glob("**/*.jsonl"))
    if not all_files:
        raise FileNotFoundError(f"在 {data_dir} 下未找到任何 .jsonl 文件")

    records = []
    for file_path in all_files:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    records.append(record)
                except json.JSONDecodeError:
                    continue

    # 随机采样，避免数据集过大
    if len(records) > max_samples:
        records = random.sample(records, max_samples)

    logger.info(f"[grpo_trainer] 加载 {len(records)} 条局面 prompt")

    # 构造 prompt（只有 system + user，不含 assistant）
    samples = []
    for record in records:
        system = SYSTEM_TEMPLATE.format(profile=record.get("profile", ""))
        user = USER_TEMPLATE.format(
            game_setup=record.get("game_setup", "")
            .replace("0 | Game setup:\n", "")
            .strip(),
            hard_facts=record.get("hard_facts", ""),
            soft_signals=record.get("soft_signals", ""),
            instruction=record.get("instruction", ""),
        )
        samples.append(
            {
                "prompt": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # metadata 用于奖励函数计算，不参与训练
                "metadata": json.dumps(
                    {
                        "profile": record.get("profile", ""),
                        "outcome": record.get("outcome", ""),
                        "winner": (
                            "werewolf"
                            if record.get("outcome") == "won"
                            and record.get("profile") == "Werewolf"
                            else (
                                "good guys"
                                if record.get("outcome") == "won"
                                else "unknown"
                            )
                        ),
                        "dead_players": {},  # 原始数据中暂无此字段，奖励函数降级处理
                        "vote_results": [],
                    },
                    ensure_ascii=False,
                ),
            }
        )

    return Dataset.from_list(samples)


# ── 奖励函数（GRPO 接口）────────────────────────────────────────────────────


def make_reward_fn(tokenizer):
    """返回符合 trl GRPOTrainer 接口的奖励函数。

    GRPOTrainer 期望签名：
        reward_fn(prompts, completions, **kwargs) -> list[float]
    """
    from werewolf_game.schema import RoleExperience

    def reward_fn(
        prompts: list[Any],
        completions: list[str],
        metadata: list[str] | None = None,
        **kwargs,
    ) -> list[float]:
        rewards = []
        for i, completion in enumerate(completions):
            meta = json.loads(metadata[i]) if metadata else {}
            profile = meta.get("profile", "Villager")
            winner = meta.get("winner", "unknown")
            game_result = {
                "winner": winner,
                "dead_players": meta.get("dead_players", {}),
                "vote_results": meta.get("vote_results", []),
            }

            # 构造临时 RoleExperience 用于奖励计算
            exp = RoleExperience(
                profile=profile,
                reflection="",
                response=completion,
                outcome=meta.get("outcome", ""),
            )

            # 终局奖励 + 过程奖励
            scored = assign_cumulative_rewards([exp], winner, game_result)
            rewards.append(scored[0].cumulative_reward)  # type: ignore[attr-defined]

        return rewards

    return reward_fn


# ── 模型加载 ─────────────────────────────────────────────────────────────────


def load_model_for_grpo(sft_checkpoint: str, base_model: str):
    """加载 SFT checkpoint，准备 GRPO 训练。

    策略：
      - 底座用 4bit 量化加载（节省显存）
      - 加载 SFT 阶段保存的 LoRA adapter 作为 Actor 初始权重
      - Reference Model 通过禁用 LoRA 实现（共享底座，不额外占用显存）
    """
    logger.info(f"[grpo_trainer] 加载底座模型：{base_model}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )

    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    base = prepare_model_for_kbit_training(base)

    # 加载 SFT LoRA adapter
    sft_path = Path(sft_checkpoint)
    if sft_path.exists() and (sft_path / "adapter_config.json").exists():
        logger.info(f"[grpo_trainer] 加载 SFT adapter：{sft_checkpoint}")
        model = PeftModel.from_pretrained(base, sft_checkpoint, is_trainable=True)
    else:
        logger.warning(f"[grpo_trainer] 未找到 SFT adapter，从头开始 GRPO 训练")
        lora_config = LoraConfig(
            r=16,
            lora_alpha=32,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            lora_dropout=0.05,
            task_type=TaskType.CAUSAL_LM,
        )
        model = get_peft_model(base, lora_config)

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    return model, tokenizer


# ── 训练主函数 ───────────────────────────────────────────────────────────────


def train(
    sft_checkpoint: str = "training/data/checkpoints/sft",
    data_path: str = "training/data/raw",
    output_dir: str = "training/data/checkpoints/grpo",
    base_model: str = DEFAULT_MODEL,
    num_epochs: int = 1,
    batch_size: int = 1,
    gradient_accumulation_steps: int = 8,
    learning_rate: float = 5e-6,
    group_size: int = GROUP_SIZE,
    max_new_tokens: int = MAX_NEW_TOKENS,
    max_seq_length: int = MAX_SEQ_LENGTH,
    max_samples: int = 2000,
    kl_coeff: float = 0.1,
    save_steps: int = 50,
    logging_steps: int = 5,
):
    """执行 GRPO 强化学习训练。

    Args:
        sft_checkpoint: SFT 阶段保存的 LoRA adapter 路径
        data_path: 原始经验数据目录（data_collector 输出）
        output_dir: GRPO LoRA adapter 保存目录
        base_model: 底座模型名称或本地路径
        num_epochs: 训练轮数
        batch_size: 每卡 batch size（4090 建议 1）
        gradient_accumulation_steps: 梯度累积步数
        learning_rate: 学习率（GRPO 通常比 SFT 小一个数量级）
        group_size: 每个局面采样的候选回复数 G
        max_new_tokens: 生成时最大新 token 数
        max_seq_length: 最大序列长度
        max_samples: 最大训练样本数
        kl_coeff: KL 散度惩罚系数（防止偏离 SFT 模型太远）
        save_steps: 每隔多少步保存一次 checkpoint
        logging_steps: 每隔多少步打印一次日志
    """
    # 1. 加载局面 prompt 数据集
    dataset = load_grpo_prompts(data_path, max_samples=max_samples)

    # 2. 加载模型
    model, tokenizer = load_model_for_grpo(sft_checkpoint, base_model)

    # 3. 构造奖励函数
    reward_fn = make_reward_fn(tokenizer)

    # 4. GRPO 训练配置
    grpo_config = GRPOConfig(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        bf16=True,
        num_generations=group_size,  # 每个 prompt 采样 G 个回复
        max_new_tokens=max_new_tokens,
        max_length=max_seq_length,
        kl_coef=kl_coeff,  # KL 惩罚，防止偏离 SFT 太远
        logging_steps=logging_steps,
        save_steps=save_steps,
        save_total_limit=3,
        report_to="none",
        remove_unused_columns=False,
    )

    # 5. 启动 GRPO 训练
    trainer = GRPOTrainer(
        model=model,
        tokenizer=tokenizer,
        reward_funcs=reward_fn,
        args=grpo_config,
        train_dataset=dataset,
    )

    logger.info("[grpo_trainer] 开始 GRPO 训练...")
    trainer.train()

    # 6. 保存 LoRA adapter
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    logger.info(f"[grpo_trainer] GRPO adapter 已保存至 {output_dir}")


if __name__ == "__main__":
    fire.Fire(train)
