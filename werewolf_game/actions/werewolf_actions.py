from werewolf_game.actions.common_actions import Speak, NighttimeWhispers


class Kill(NighttimeWhispers):
    def __init__(self, name="Kill", context=None, llm=None):
        super().__init__(name, context, llm)


class Impersonate(Speak):
    """Action: werewolf impersonating a good guy in daytime speak"""

    STRATEGY = """
    Try continuously impersonating a role, such as Seer, Witch, Villager, etc., in order to mislead
    other players, make them trust you, and thus hiding your werewolf identity. However, pay attention to what your werewolf partner said, 
    DONT claim the same role as your werewolf partner. Remember NOT to reveal your real identity as a werewolf!
    """

    def __init__(self, name="Impersonate", context=None, llm=None):
        super().__init__(name, context, llm)
