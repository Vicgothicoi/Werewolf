# 把各角色的action类统一从子模块里导入
from werewolf_game.actions.moderator_actions import InstructSpeak
from werewolf_game.actions.common_actions import (
    Speak,
    NighttimeWhispers,
    Reflect,
    Summarize,
)
from werewolf_game.actions.werewolf_actions import Kill, Impersonate
from werewolf_game.actions.hunter_actions import Hunt
from werewolf_game.actions.seer_actions import Verify
from werewolf_game.actions.witch_actions import Save, Poison

# action 名称（字符串）映射到对应的类，方便通过名字动态查找和实例化 action
ACTIONS = {
    "Speak": Speak,
    "Kill": Kill,
    "Hunt": Hunt,
    "Verify": Verify,
    "Save": Save,
    "Poison": Poison,
    "Impersonate": Impersonate,
}
