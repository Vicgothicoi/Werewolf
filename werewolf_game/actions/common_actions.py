from metagpt.actions import Action
from metagpt.const import WORKSPACE_ROOT
from metagpt.logs import logger
from tenacity import retry, stop_after_attempt, wait_fixed
import json

# ---------------------------------------------------------------------------
# Tool schemas — used by Function Calling to guarantee structured output
# ---------------------------------------------------------------------------

SPEAK_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_speak",
        "description": "Submit your speech or vote in the Werewolf game",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Your role in the game"},
                "player_name": {"type": "string", "description": "Your player name"},
                "living_players": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of currently living players",
                },
                "thoughts": {
                    "type": "string",
                    "description": "Step-by-step reasoning (max 3 steps)",
                },
                "response": {
                    "type": "string",
                    "description": "Your speech or vote, following the moderator's instruction",
                },
            },
            "required": [
                "role",
                "player_name",
                "living_players",
                "thoughts",
                "response",
            ],
        },
    },
}

NIGHTTIME_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_night_action",
        "description": "Submit your nighttime action in the Werewolf game",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Your role in the game"},
                "player_name": {"type": "string", "description": "Your player name"},
                "living_players": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of currently living players",
                },
                "thoughts": {
                    "type": "string",
                    "description": "Step-by-step reasoning for your choice (max 3 steps)",
                },
                "response": {
                    "type": "string",
                    "description": "The name of the player you choose to act on (player name ONLY)",
                },
            },
            "required": [
                "role",
                "player_name",
                "living_players",
                "thoughts",
                "response",
            ],
        },
    },
}

REFLECT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_reflection",
        "description": "Submit your game state analysis and reflection",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "player_name": {"type": "string"},
                "hard_facts": {
                    "type": "string",
                    "description": (
                        "Objective facts only — no inference. "
                        "A JSON-formatted string representing a list of per-player status objects, each with keys: "
                        "target, status (living/dead), death_cause (killed by vote / killed at night / unknown / None if living)."
                    ),
                },
                "soft_signals": {
                    "type": "string",
                    "description": (
                        "Behavioral observations and speech analysis. "
                        "A JSON-formatted string representing a list of per-player observation objects, each with keys: "
                        "target, claimed_role, side_with, accuse."
                    ),
                },
                "reflection": {
                    "type": "string",
                    "description": (
                        "Role inference per player based on hard_facts and soft_signals. "
                        "A JSON-formatted string: keys are player names, values are inferred role descriptions. "
                        "Must also include a GAME_STATE_SUMMARIZATION key with a one-sentence summary."
                    ),
                },
            },
            "required": [
                "role",
                "player_name",
                "hard_facts",
                "soft_signals",
                "reflection",
            ],
        },
    },
}


class Speak(Action):
    """Action: Any speak action in a game"""

    PROMPT_TEMPLATE = """
    {
    "BACKGROUND": "It's a Werewolf game. __game_setup__ You are __profile__. Note that villager, seer, hunter and witch are all in villager side, they have the same objective. Werewolves can collectively kill ONE player at night."
    ,"HISTORY": "You have knowledge to the following conversation: __context__"
    ,"ATTENTION": "You can NOT VOTE a player who is NOT ALIVE now!"
    ,"REFLECTION": "__reflection__"
    ,"STRATEGY": __strategy__
    ,"PAST_EXPERIENCES": "__experiences__"
    ,"MODERATOR_INSTRUCTION": __latest_instruction__,
    ,"RULE": "Please follow the moderator's latest instruction, figure out if you need to speak your opinion or directly to vote:
              1. If the instruction is to SPEAK, speak in 200 words. Remember the goal of your role and try to achieve it using your speech;
              2. If the instruction is to VOTE, you MUST vote and ONLY say 'I vote to eliminate PlayerX', REPLACE PlayerX with the actual player name, you CANT say nothing, DO NOT include any other words. "
    ,"OUTPUT_FORMAT":
        {
        "ROLE": "Your role, in this case, __profile__"
        ,"PLAYER_NAME": "Your name, in this case, __name__"
        ,"LIVING_PLAYERS": "List living players based on MODERATOR_INSTRUCTION. Return a json LIST datatype."
        ,"THOUGHTS": "Based on `MODERATOR_INSTRUCTION` and `RULE`, carefully think about what to say or vote so that your chance of win as __profile__ maximizes.
                      If you find similar situation in `PAST_EXPERIENCES`, you may draw lessons from them to refine your strategy, take better vote action, or improve your speech.
                      Give your step-by-step thought process, you should think no more than 3 steps. For example: My step-by-step thought process:..."
        ,"RESPONSE": "Based on `MODERATOR_INSTRUCTION`, `RULE`, and the 'THOUGHTS' you had, express your opinion or cast a vote."
        }
    }
    """
    STRATEGY = """
    Decide whether to reveal your identity based on benefits vs. risks, provide useful information, and vote to eliminate the most suspicious.
    If you have special abilities, pay attention to those who falsely claims your role, for they are probably werewolves.
    """

    def __init__(self, name="Speak", context=None, llm=None):
        # 调用父类的初始化方法
        super().__init__(name, context, llm)

    #  tenacity 库的重试装饰器。意思是：如果被装饰的函数抛出异常，最多重试 2 次，每次重试前等待 1 秒
    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
    async def run(
        self,
        profile: str,
        name: str,
        context: str,
        latest_instruction: str,
        reflection: str = "",
        experiences: str = "",
        game_setup: str = "",
    ):

        prompt = (
            self.PROMPT_TEMPLATE.replace("__context__", context)
            .replace("__profile__", profile)
            .replace("__name__", name)
            .replace("__latest_instruction__", latest_instruction)
            .replace("__strategy__", self.STRATEGY)
            .replace("__reflection__", reflection)
            .replace("__experiences__", experiences)
            .replace("__game_setup__", game_setup)
        )

        # 通过 Function Calling 强制结构化输出
        rsp_dict = await self._aask_tool(prompt, [SPEAK_TOOL], "submit_speak")

        print("--------------------思维链--------------------")
        print(rsp_dict["thoughts"])
        print("----------------------------------------------")

        return rsp_dict["response"]


class NighttimeWhispers(Action):
    PROMPT_TEMPLATE = """
    {
    "BACKGROUND": "It's a Werewolf game. __game_setup__ You are __profile__. Note that villager, seer, hunter and witch are all in villager side, they have the same objective. Werewolves can collectively kill ONE player at night."
    ,"HISTORY": "You have knowledge to the following conversation: __context__"
    ,"ACTION": "Choose one living player to __action__."
    ,"ATTENTION": "1. You can only __action__ a player who is alive this night! And you can not __action__ a player who is dead this night!  2. `HISTORY` is all the information you observed, DONT hallucinate other player actions!"
    ,"REFLECTION": "__reflection__"
    ,"STRATEGY": "__strategy__"
    ,"PAST_EXPERIENCES": "__experiences__"
    ,"OUTPUT_FORMAT":
        {
        "ROLE": "Your role, in this case, __profile__"
        ,"PLAYER_NAME": "Your name, in this case, __name__"
        ,"LIVING_PLAYERS": "List the players who is alive based on moderator's latest instruction. Return a json LIST datatype."
        ,"THOUGHTS": "Choose one living player from `LIVING_PLAYERS` to __action__ this night. Return the reason why you choose to __action__ this player. If you observe nothing at first night, DONT imagine unexisting player actions! If you find similar situation in `PAST_EXPERIENCES`, you may draw lessons from them to refine your strategy and take better actions. Give your step-by-step thought process, you should think no more than 3 steps. For example: My step-by-step thought process:..."
        ,"RESPONSE": "As a __profile__, you should choose one living player from `LIVING_PLAYERS` to __action__ this night according to the THOUGHTS you have just now. Return the player name ONLY."
        }
    }
    """
    STRATEGY = """
    Decide which player is most threatening to you or most needs your support, take your action correspondingly.
    """
    #    If you are werewolf, Kill Player 5 in first night.

    def __init__(self, name="NightTimeWhispers", context=None, llm=None):
        super().__init__(name, context, llm)

    def _construct_prompt_json(
        self,
        role_profile: str,
        role_name: str,
        context: str,
        reflection: str,
        experiences: str,
        game_setup: str = "",
        **kwargs,
    ):
        prompt_template = self.PROMPT_TEMPLATE

        def replace_string(prompt_json: dict):
            k: str
            for k in prompt_json.keys():
                # 递归遍历键值替换所有的占位符
                if isinstance(prompt_json[k], dict):
                    prompt_json[k] = replace_string(prompt_json[k])
                    continue
                prompt_json[k] = prompt_json[k].replace("__profile__", role_profile)
                prompt_json[k] = prompt_json[k].replace("__name__", role_name)
                prompt_json[k] = prompt_json[k].replace("__context__", context)
                prompt_json[k] = prompt_json[k].replace("__action__", self.name)
                prompt_json[k] = prompt_json[k].replace("__strategy__", self.STRATEGY)
                prompt_json[k] = prompt_json[k].replace("__reflection__", reflection)
                prompt_json[k] = prompt_json[k].replace("__experiences__", experiences)
                prompt_json[k] = prompt_json[k].replace("__game_setup__", game_setup)

            return prompt_json

        # 将一个符合JSON语法的字符串解析为一个Python字典对象
        prompt_json: dict = json.loads(prompt_template)

        prompt_json = replace_string(prompt_json)

        prompt_json: dict = self._update_prompt_json(
            prompt_json,
            role_profile,
            role_name,
            context,
            reflection,
            experiences,
            game_setup=game_setup,
            **kwargs,
        )
        assert isinstance(prompt_json, dict)

        prompt: str = json.dumps(prompt_json, indent=4, ensure_ascii=False)

        return prompt

    def _update_prompt_json(
        self,
        prompt_json: dict,
        role_profile: str,
        role_name: str,
        context: str,
        reflection: str,
        experiences: str,
        game_setup: str = "",
    ) -> dict:
        # one can modify the prompt_json dictionary here
        return prompt_json

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
    async def run(
        self,
        context: str,
        profile: str,
        name: str,
        reflection: str = "",
        experiences: str = "",
        game_setup: str = "",
    ):

        prompt = self._construct_prompt_json(
            role_profile=profile,
            role_name=name,
            context=context,
            reflection=reflection,
            experiences=experiences,
            game_setup=game_setup,
        )

        # 通过 Function Calling 强制结构化输出
        rsp_dict = await self._aask_tool(
            prompt, [NIGHTTIME_TOOL], "submit_night_action"
        )

        print("--------------------思维链--------------------")
        print(rsp_dict["thoughts"])
        print("----------------------------------------------")
        return f"{self.name} " + rsp_dict["response"]


class Reflect(Action):

    PROMPT_TEMPLATE = """
    {
    "BACKGROUND": "It's a Werewolf game. __game_setup__ You are __profile__. Note that villager, seer, hunter and witch are all in villager side, they have the same objective. Werewolves can collectively kill ONE player at night."
    ,"HISTORY": "You have knowledge to the following conversation: __context__"
    ,"MODERATOR_INSTRUCTION": __latest_instruction__,
    ,"OUTPUT_FORMAT" (a json):
        {
        "ROLE": "Your role, in this case, __profile__"
        ,"PLAYER_NAME": "Your name, in this case, __name__"
        ,"HARD_FACTS": "Observe objective facts only, do NOT infer or interpret. Return a LIST of jsons:
                        [
                            {"TARGET": "the player you will analyze, if the player is yourself or your werewolf partner, indicate it", "STATUS": "living or dead", "DEATH_CAUSE": "killed by vote / killed at night / unknown / None if living"}
                            ,{...}
                            ,...
                        ]"
        ,"SOFT_SIGNALS": "Observe behavior and speech, return a LIST of jsons:
                        [
                            {"TARGET": "the player you will analyze, if the player is yourself or your werewolf partner, indicate it", "CLAIMED_ROLE": "claims a role or not, if so, what role, any contradiction to others? If there is no claim, return 'None' ", "SIDE_WITH": "sides with which players? If none, return 'None' ", "ACCUSE": "accuses which players? If none, return 'None' "}
                            ,{...}
                            ,...
                        ]"
        ,"REFLECTION": "Based on `HARD_FACTS` and `SOFT_SIGNALS`, return a json:
                       {
                            "PlayerX(replace X with the player you will analyze)": "the true role (werewolf / special role / villager, living or dead) you infer about him/her, and why is this role? If the player is yourself or your werewolf partner, indicate it."
                            ,...
                            ,"GAME_STATE_SUMMARIZATION": "summarize the current situation from your standpoint in one sentence, your summarization should catch the most important information from your reflection, such as conflicts, number of living werewolves, special roles, and villagers."
                       }"
        ,"STRATEGY": "__strategy__"
        }
    }
    """
    # (return an empty string for the first night)
    # that do not include Escape Character `\`
    # that do not include Escape Character `\`(return an empty LIST for the first night)
    STRATEGY = """
    Make your `REFLECTION` conscientiously.
    """

    def __init__(self, name="Reflect", context=None, llm=None):
        super().__init__(name, context, llm)

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
    async def run(
        self,
        profile: str,
        name: str,
        context: str,
        latest_instruction: str,
        game_setup: str = "",
    ):

        prompt = (
            self.PROMPT_TEMPLATE.replace("__context__", context)
            .replace("__profile__", profile)
            .replace("__name__", name)
            .replace("__latest_instruction__", latest_instruction)
            .replace("__strategy__", self.STRATEGY)
            .replace("__game_setup__", game_setup)
        )

        # 通过 Function Calling 强制结构化输出
        rsp_dict = await self._aask_tool(prompt, [REFLECT_TOOL], "submit_reflection")

        print("--------------------反思结果--------------------")
        for k, v in json.loads(rsp_dict["reflection"]).items():
            print(f"{k}: {v}")
        print("-----------------------------------------------")

        return (
            rsp_dict["hard_facts"],
            rsp_dict["soft_signals"],
            rsp_dict["reflection"],
        )


class Summarize(Action):

    PROMPT_TEMPLATE = """
    "BACKGROUND": "It's a Werewolf game. __game_setup__ You are __profile__. Note that villager, seer, hunter and witch are all in villager side, they have the same objective. Werewolves can collectively kill ONE player at night."
    ,"HISTORY": "You have knowledge to the following conversation: __context__"
    ,"REFLECTION": "__reflection__"
    ,Your REFLECTION is based on the HISTORY, You should find the strategy that how do you Derive this REFLECTION and return in 60 words.
    """

    def __init__(self, name="Summarize", context=None, llm=None):
        super().__init__(name, context, llm)

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
    async def run(
        self,
        context: str,
        reflection: str = "",
        profile: str = "",
        game_setup: str = "",
    ):

        prompt = (
            self.PROMPT_TEMPLATE.replace("__context__", context)
            .replace("__reflection__", reflection)
            .replace("__profile__", profile)
            .replace("__game_setup__", game_setup)
        )

        rsp = await self._aask(prompt)

        return rsp
