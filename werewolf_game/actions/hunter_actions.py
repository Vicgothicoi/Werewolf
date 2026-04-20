from werewolf_game.actions import NighttimeWhispers, Reflect


class Hunt(NighttimeWhispers):
    def __init__(self, name="Hunt", context=None, llm=None):
        super().__init__(name, context, llm)
