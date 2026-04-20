from pydantic import BaseModel


# 继承BaseModel类：自动类型验证、转换，当字段缺失或类型错误时立即报错
class RoleExperience(BaseModel):
    id: str = ""
    name: str = ""
    profile: str
    reflection: str
    hard_facts: str = ""  # 客观事实：存活/死亡状态，用于 embedding 检索
    soft_signals: str = ""  # 行为观测：发言、指控、阵营倾向，存入 metadata 不参与检索
    instruction: str = ""
    response: str
    outcome: str = ""
    round_id: str = ""
    game_setup: str = ""
    version: str = ""
