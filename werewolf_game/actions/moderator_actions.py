from metagpt.actions import Action

STEP_INSTRUCTIONS = {  # 字典
    # 上帝需要介入的全部步骤和对应指令
    # The 1-st night
    0: {
        "content": "It’s dark, everyone close your eyes. I will talk with you/your team secretly at night.",
        "send_to": "Moderator",  # for moderator to continue speaking
        "restricted_to": "",
    },
    1: {
        "content": "Werewolves, please open your eyes!",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    2: {
        "content": """Werewolves, I secretly tell you that {werewolf_players} are all of the werewolves! Keep in mind you are teammates. The rest players are not werewolves.
                   choose one from the following living options please:
                   {living_players}. For example: Kill ...""",
        "send_to": "Werewolf",
        "restricted_to": "Moderator,Werewolf",
    },
    3: {
        "content": "Werewolves, close your eyes",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    4: {
        "content": "Witch, please open your eyes!",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    5: {
        "content": """Witch, tonight {player_killed} has been killed by the werewolves.
                   You have a bottle of antidote, would you like to save him/her? If so, say "Save", else, say "Pass".""",
        "send_to": "Witch",
        "restricted_to": "Moderator,Witch",
    },  # 要先判断女巫是否有解药，再去询问女巫是否使用解药救人
    6: {
        "content": """Witch, you also have a bottle of poison, would you like to use it to kill one of the living players?
                   Choose one from the following living options: {living_players}.
                   If so, say ONLY "Poison PlayerX", replace PlayerX with the actual player name, else, say "Pass".""",
        "send_to": "Witch",
        "restricted_to": "Moderator,Witch",
    },
    7: {
        "content": "Witch, close your eyes",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    8: {
        "content": "Seer, please open your eyes!",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    9: {
        "content": """Seer, you can check one player's identity. Who are you going to verify its identity tonight?
                    Choose only one from the following living options:{living_players}.""",
        "send_to": "Seer",
        "restricted_to": "Moderator,Seer",
    },
    10: {
        "content": "Seer, close your eyes",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    # The 1-st daytime
    11: {
        "content": """It's daytime. Everyone woke up except those who had been killed.""",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    12: {
        "content": "{player_current_dead} was killed last night!",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    13: {
        "content": """You are killed , choose one player from the following living options to hunt please:
                   {living_players}. For example: Hunt ...""",
        "send_to": "Hunter",
        "restricted_to": "Moderator,Hunter",
    },
    14: {
        "content": """{player_current_dead} was hunted by hunter.""",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    15: {
        "content": """Living players: {living_players}, now freely talk about the current situation based on your observation and reflection with a few sentences. Decide whether to reveal your identity based on your reflection.""",
        "send_to": "",  # send to all to speak in daytime
        "restricted_to": "",
    },
    16: {
        "content": """Now vote and tell me who you think is the werewolf. Don’t mention your role.
                    You only choose one from the following living options please:
                    {living_players}. Say ONLY: I vote to eliminate ...""",
        "send_to": "",
        "restricted_to": "",
    },
    17: {
        "content": """{player_current_dead} was eliminated.""",
        "send_to": "Moderator",
        "restricted_to": "",
    },
    18: {
        "content": """You are eliminated, choose one player from the following living options to hunt please:
                   {living_players}. For example: Hunt ...""",
        "send_to": "Hunter",
        "restricted_to": "Moderator,Hunter",
    },
    19: {
        "content": """{player_current_dead} was hunted by hunter.""",
        "send_to": "Moderator",
        "restricted_to": "",
    },
}


class InstructSpeak(Action):
    def __init__(self, name="InstructSpeak", context=None, llm=None):
        super().__init__(name, context, llm)

    async def run(
        self,
        step_idx,
        living_players,
        werewolf_players,
        player_killed,
        player_current_dead,
    ):
        instruction_info = STEP_INSTRUCTIONS.get(
            step_idx,
            {  # 返回默认值
                "content": "Unknown instruction.",
                "send_to": "",
                "restricted_to": "",
            },
        )
        content = instruction_info["content"]
        if "{living_players}" in content and "{werewolf_players}" in content:
            content = content.format(
                living_players=living_players, werewolf_players=werewolf_players
            )
        elif "{living_players}" in content:
            content = content.format(living_players=living_players)
        elif "{werewolf_players}" in content:
            content = content.format(werewolf_players=werewolf_players)
        if "{player_killed}" in content:
            content = content.format(player_killed=player_killed)
        if "{player_current_dead}" in content:
            player_current_dead = (
                "No one" if not player_current_dead else player_current_dead
            )
            content = content.format(player_current_dead=player_current_dead)

        return content, instruction_info["send_to"], instruction_info["restricted_to"]


class ParseSpeak(Action):
    def __init__(self, name="ParseSpeak", context=None, llm=None):
        super().__init__(name, context, llm)

    async def run(self):
        pass


class AnnounceGameResult(Action):
    async def run(self, winner: str, win_reason: str):
        return f"Game over! {win_reason}. The winner is the {winner}"
