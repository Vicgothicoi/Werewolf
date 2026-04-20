from metagpt.roles import Role
from werewolf_game.roles.base_player import BasePlayer


class Hunter(BasePlayer):
    def __init__(
        self,
        name: str = "",
        profile: str = "Hunter",
        special_action_names: list[str] = ["Hunt"],
        **kwargs,
    ):
        super().__init__(name, profile, special_action_names, **kwargs)
        self.has_acted_after_death = False  # 死后是否已经行动过

    async def _observe(self) -> int:
        """猎人死后还要发言一次，因此需要重写 _observe。
        死亡后仅允许行动一次，之后不再参与游戏。"""
        if self.status == 1 and self.has_acted_after_death:
            return 0

        # 绕过 BasePlayer 的死亡拦截，直接调用 Role._observe
        await Role._observe(self)
        self._rc.news = [
            msg for msg in self._rc.news if msg.send_to in ["", self.profile]
        ]

        # 死亡后收到有效消息（猎杀指令），标记本次为唯一一次行动机会
        if self.status == 1 and len(self._rc.news) > 0:
            self.has_acted_after_death = True

        return len(self._rc.news)
