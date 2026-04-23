import re
from collections import Counter
from datetime import datetime

from metagpt.const import WORKSPACE_ROOT
from metagpt.roles import Role
from metagpt.schema import Message
from metagpt.logs import logger
from metagpt.actions import BossRequirement as UserRequirement
from werewolf_game.actions.moderator_actions import (
    InstructSpeak,
    ParseSpeak,
    AnnounceGameResult,
    STEP_INSTRUCTIONS,
)
from werewolf_game.actions import Kill, Verify, Save, Poison, Hunt


class Moderator(Role):

    def __init__(
        self,
        name: str = "Moderator",
        profile: str = "Moderator",
        **kwargs,
    ):
        super().__init__(name, profile, **kwargs)
        self._watch([UserRequirement, InstructSpeak, ParseSpeak])
        self._init_actions([InstructSpeak, ParseSpeak, AnnounceGameResult])
        self.step_idx = 0
        # self.eval_step_idx = []

        # game states
        self.game_setup = ""
        self.living_players = []
        self.werewolf_players = []
        self.villager_players = []
        self.special_role_players = []
        self.hunter_players = []

        self.winner = None
        self.win_reason = None
        self.witch_poison_left = 1
        self.witch_antidote_left = 1

        # player states of current night
        self.player_killed = None
        self.is_killed_player_saved = False
        self.player_poisoned = None
        self.player_hunted = None
        self.player_current_dead = []

    def _parse_game_setup(self, game_setup: str):
        self.game_setup = game_setup
        self.living_players = re.findall(r"Player[0-9]+", game_setup)
        self.werewolf_players = re.findall(r"Player[0-9]+: Werewolf", game_setup)
        self.werewolf_players = [
            p.replace(": Werewolf", "") for p in self.werewolf_players
        ]
        self.villager_players = re.findall(r"Player[0-9]+: Villager", game_setup)
        self.villager_players = [
            p.replace(": Villager", "") for p in self.villager_players
        ]
        self.hunter_players = re.findall(r"Player[0-9]+: Hunter", game_setup)
        self.hunter_players = [p.replace(": Hunter", "") for p in self.hunter_players]
        self.special_role_players = [
            p
            for p in self.living_players
            if p not in self.werewolf_players + self.villager_players
        ]

        # print("状态初始化：", self.hunter_players)

    def update_player_status(self, player_names: list[str]):
        if not player_names:
            return
        roles_in_env = self._rc.env.get_roles()
        for role_setting, role in roles_in_env.items():
            for player_name in player_names:
                if player_name in role_setting:
                    role.set_status(new_status=1)  # 更新为死亡

    def _record_all_experiences(self):
        roles_in_env = self._rc.env.get_roles()
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        for _, role in roles_in_env.items():
            if role == self:
                continue
            if self.winner == "werewolf":
                outcome = "won" if role.name in self.werewolf_players else "lost"
            else:
                outcome = "won" if role.name not in self.werewolf_players else "lost"
            role.record_experiences(
                round_id=timestamp, outcome=outcome, game_setup=self.game_setup
            )

    def _get_current_step_idx(self) -> tuple[int, int]:
        """计算当前应执行的步骤编号，统一处理 Hunter/Witch 的跳步逻辑。
        返回 (step_idx_mod, step_idx_abs)：取模后的步骤编号（0-19）和跳步后的绝对值。"""
        n = len(STEP_INSTRUCTIONS)
        abs_idx = self.step_idx
        step_idx = abs_idx % n

        # 跳过 Hunter 步骤：场上没有 Hunter，或本轮死亡玩家中没有 Hunter
        has_hunter_died = any(
            p in self.player_current_dead for p in self.hunter_players
        )
        if (step_idx == 13 or step_idx == 18) and not has_hunter_died:
            abs_idx += 2
            step_idx = abs_idx % n

        # 跳过 Witch 步骤（步骤 4-7）：当局没有 Witch 角色
        has_witch = "Witch" in self.game_setup
        if step_idx in [4, 5, 6, 7] and not has_witch:
            abs_idx += 8 - step_idx
            step_idx = abs_idx % n

        return step_idx, abs_idx

    async def _instruct_speak(self):
        step_idx, abs_idx = self._get_current_step_idx()
        self.step_idx = abs_idx + 1  # 推进到下一步
        return await InstructSpeak().run(
            step_idx,
            living_players=self.living_players,
            werewolf_players=self.werewolf_players,
            player_killed=self.player_killed,
            player_current_dead=self.player_current_dead,
        )

    async def _parse_speak(self, memories):
        # logger.info(self.step_idx)

        latest_msg = memories[-1]
        latest_msg_content = latest_msg.content

        match = re.search(r"Player[0-9]+", latest_msg_content)
        target = match.group(0) if match else ""

        # default return
        msg_content = "Understood"
        restricted_to = ""

        msg_cause_by = latest_msg.cause_by
        if msg_cause_by == Kill:
            self.player_killed = target
        elif msg_cause_by == Verify:
            if target in self.werewolf_players:
                msg_content = f"{target} is a werewolf"
            else:
                msg_content = f"{target} is a good guy"
            restricted_to = "Moderator,Seer"
        elif msg_cause_by == Save:
            if "pass" in latest_msg_content.lower():
                pass
            elif not self.witch_antidote_left:
                msg_content = (
                    "You have no antidote left and thus can not save the player"
                )
                restricted_to = "Moderator,Witch"
            else:
                self.witch_antidote_left -= 1
                self.is_killed_player_saved = True
        elif msg_cause_by == Poison:
            if "pass" in latest_msg_content.lower():
                pass
            elif not self.witch_poison_left:
                msg_content = (
                    "You have no poison left and thus can not poison the player"
                )
                restricted_to = "Moderator,Witch"
            else:
                self.witch_poison_left -= 1
                self.player_poisoned = (
                    target  # "" if not poisoned and "PlayerX" if poisoned
                )

        elif msg_cause_by == Hunt:
            self.player_hunted = target

        # print("解析对话：",self.step_idx,self.player_hunted)

        return msg_content, restricted_to

    def _update_game_states(self, memories):

        step_idx, _ = self._get_current_step_idx()
        if step_idx not in [12, 14, 17, 19]:
            return
        # else:
        #    self.eval_step_idx.append(self.step_idx)
        # record evaluation, avoid repetitive evaluation at the same step

        if step_idx == 12 or step_idx == 14 or step_idx == 19:  # FIXME: hard code
            # night ends: after all special roles acted, process the whole night
            self.player_current_dead = []  # reset

            if self.player_killed and not self.is_killed_player_saved:
                self.player_current_dead.append(self.player_killed)
            if self.player_poisoned:
                self.player_current_dead.append(self.player_poisoned)
            if self.player_hunted:
                self.player_current_dead.append(self.player_hunted)

            # print("更新状态：",self.step_idx,self.player_hunted)

            self.living_players = [
                p for p in self.living_players if p not in self.player_current_dead
            ]
            self.update_player_status(self.player_current_dead)
            # reset
            self.player_killed = None
            self.player_hunted = None
            self.is_killed_player_saved = False
            self.player_poisoned = None

        elif step_idx == 17:
            # day ends: after all roles voted, process all votings
            voting_msgs = memories[-(len(self.living_players) + 2) :]
            print("投票消息：", type(voting_msgs), voting_msgs)
            voted_all = []
            for msg in voting_msgs:
                if msg.sent_from == "Moderator":
                    continue
                voted = re.search(r"Player[0-9]+", msg.content)
                if not voted:
                    continue
                voted_all.append(voted.group(0))
            vote_count = Counter(voted_all)
            self.player_current_dead = [
                max(vote_count, key=lambda p: (vote_count[p], -voted_all.index(p)))
            ]  # 平票时，杀最先被投的
            self.living_players = [
                p for p in self.living_players if p not in self.player_current_dead
            ]
            self.update_player_status(self.player_current_dead)

        # game's termination condition
        living_werewolf = [p for p in self.werewolf_players if p in self.living_players]
        living_villagers = [
            p for p in self.villager_players if p in self.living_players
        ]
        living_special_roles = [
            p for p in self.special_role_players if p in self.living_players
        ]
        if not living_werewolf:
            self.winner = "good guys"
            self.win_reason = "werewolves all dead"
        elif not living_villagers or not living_special_roles:
            self.winner = "werewolf"
            self.win_reason = (
                "villagers all dead"
                if not living_villagers
                else "special roles all dead"
            )
        if self.winner is not None:
            self._record_all_experiences()

    def _record_game_history(self):
        if self.step_idx % len(STEP_INSTRUCTIONS) == 0 or self.winner is not None:
            logger.info("a night and day cycle completed, examine all history")
            print(self.get_all_memories())
            with open(WORKSPACE_ROOT / "werewolf_transcript.txt", "w") as f:
                f.write(self.get_all_memories())

    async def _think(self):

        if self.winner is not None:
            self._rc.todo = AnnounceGameResult()
            return

        latest_msg = self._rc.memory.get()[-1]
        if latest_msg.role in ["User"]:
            # 上一轮消息是用户指令，解析用户指令，开始游戏
            game_setup = latest_msg.content
            self._parse_game_setup(game_setup)
            self._rc.todo = InstructSpeak()

        elif latest_msg.role in [self.profile]:
            # 上一条是 Moderator 自己发的（send_to="Moderator" 的步骤），继续推进
            self._rc.todo = InstructSpeak()

        else:
            # 上一轮消息是游戏角色的发言，解析角色的发言
            self._rc.todo = ParseSpeak()

    async def _act(self):
        todo = self._rc.todo

        # logger.info(f"{self._setting} ready to {todo}")

        memories = self.get_all_memories(mode="msg")

        # 若进行完一夜一日的循环，打印和记录一次完整发言历史
        self._record_game_history()

        # 每一步结束，对上步骤的死者进行总结，并更新游戏状态
        self._update_game_states(memories)

        # 根据_think的结果，执行InstructSpeak还是ParseSpeak, 并将结果返回
        if isinstance(todo, InstructSpeak):
            msg_content, msg_to_send_to, msg_restriced_to = await self._instruct_speak()
            # msg_content = f"Step {self.step_idx}: {msg_content}" # HACK: 加一个unique的step_idx避免记忆的自动去重
            msg = Message(
                content=msg_content,
                role=self.profile,
                sent_from=self.name,
                cause_by=InstructSpeak,
                send_to=msg_to_send_to,
                restricted_to=msg_restriced_to,
            )

        elif isinstance(todo, ParseSpeak):
            msg_content, msg_restriced_to = await self._parse_speak(memories)
            # msg_content = f"Step {self.step_idx}: {msg_content}" # HACK: 加一个unique的step_idx避免记忆的自动去重
            msg = Message(
                content=msg_content,
                role=self.profile,
                sent_from=self.name,
                cause_by=ParseSpeak,
                send_to="",
                restricted_to=msg_restriced_to,
            )

        elif isinstance(todo, AnnounceGameResult):
            msg_content = await AnnounceGameResult().run(
                winner=self.winner, win_reason=self.win_reason
            )
            msg = Message(
                content=msg_content,
                role=self.profile,
                sent_from=self.name,
                cause_by=AnnounceGameResult,
            )
            # 通知 server 更新 Redis 里的胜负记录
            try:
                from werewolf_game.server import update_game_result

                update_game_result(self.winner, self.win_reason)
            except Exception:
                pass

        logger.info(f"{self._setting}: {msg_content}")

        return msg

    def get_all_memories(self, mode="str") -> str:
        memories = self._rc.memory.get()
        if mode == "str":
            memories = [f"{m.sent_from}({m.role}): {m.content}" for m in memories]
            memories = "\n".join(memories)
        return memories
