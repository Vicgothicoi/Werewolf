"""
监督微调（SFT）训练脚本。

基于 QLoRA 微调 DeepSeek-R1-Distill-Qwen-7B，
使用 sft_data_builder 构建的训练集。

依赖：
    pip install transformers peft trl bitsandbytes accelerate

用法：
    python -m training.sft_trainer \
        --data_path training/data/sft.jsonl \
        --output_dir training/data/checkpoints/sft \
        --model_name deepseek-ai/DeepSeek-R1-Distill-Qwen-7B
"""

from __future__ import annotations

import json
from pathlib import Path

import fire
import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from trl import SFTTrainer, DataCollatorForCompletionOnlyLM

from metagpt.logs import logger


# ── 默认超参数 ───────────────────────────────────────────────────────────────

DEFAULT_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
MAX_SEQ_LENGTH = 2048


# ── 数据加载 ─────────────────────────────────────────────────────────────────


def load_dataset_from_jsonl(data_path: str) -> Dataset:
    """加载 sft.jsonl，转换为 HuggingFace Dataset。"""
    records = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        raise ValueError(f"训练集为空：{data_path}")

    logger.info(f"[sft_trainer] 加载 {len(records)} 条训练样本")
    return Dataset.from_list(records)


def format_messages(example: dict, tokenizer) -> dict:
    """将 messages 列表转换为模型输入文本。"""
    text = tokenizer.apply_chat_template(
        example["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}


# ── 模型加载 ─────────────────────────────────────────────────────────────────


def load_model_and_tokenizer(model_name: str):
    """加载 4bit 量化模型和 tokenizer。"""
    logger.info(f"[sft_trainer] 加载模型：{model_name}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    return model, tokenizer


def apply_lora(model) -> object:
    """为模型添加 LoRA adapter。"""
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    return model


# ── 训练主函数 ───────────────────────────────────────────────────────────────


def train(
    data_path: str = "training/data/sft.jsonl",
    output_dir: str = "training/data/checkpoints/sft",
    model_name: str = DEFAULT_MODEL,
    num_epochs: int = 3,
    batch_size: int = 2,
    gradient_accumulation_steps: int = 8,
    learning_rate: float = 2e-4,
    warmup_ratio: float = 0.1,
    max_seq_length: int = MAX_SEQ_LENGTH,
    save_steps: int = 100,
    logging_steps: int = 10,
):
    """执行 SFT 训练。

    Args:
        data_path: SFT 训练集路径（sft.jsonl）
        output_dir: LoRA adapter 保存目录
        model_name: 基础模型名称或本地路径
        num_epochs: 训练轮数
        batch_size: 每卡 batch size（4090 建议 2）
        gradient_accumulation_steps: 梯度累积步数（等效 batch = batch_size * steps）
        learning_rate: 学习率
        warmup_ratio: 学习率预热比例
        max_seq_length: 最大序列长度
        save_steps: 每隔多少步保存一次 checkpoint
        logging_steps: 每隔多少步打印一次日志
    """
    # 1. 加载数据
    dataset = load_dataset_from_jsonl(data_path)

    # 2. 加载模型
    model, tokenizer = load_model_and_tokenizer(model_name)
    model = apply_lora(model)

    # 3. 格式化数据集
    dataset = dataset.map(
        lambda x: format_messages(x, tokenizer),
        remove_columns=dataset.column_names,
    )

    # 4. 训练参数
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        warmup_ratio=warmup_ratio,
        lr_scheduler_type="cosine",
        bf16=True,
        logging_steps=logging_steps,
        save_steps=save_steps,
        save_total_limit=3,
        report_to="none",  # 可改为 "wandb" 启用实验追踪
        dataloader_num_workers=0,
    )

    # 5. 启动训练
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=max_seq_length,
        args=training_args,
    )

    logger.info("[sft_trainer] 开始训练...")
    trainer.train()

    # 6. 保存 LoRA adapter
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    logger.info(f"[sft_trainer] LoRA adapter 已保存至 {output_dir}")


if __name__ == "__main__":
    fire.Fire(train)
