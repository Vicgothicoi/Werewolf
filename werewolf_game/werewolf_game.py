from metagpt.software_company import SoftwareCompany
from metagpt.environment import Environment
from metagpt.actions import BossRequirement as UserRequirement
from metagpt.schema import Message


class WerewolfEnvironment(Environment):
    # 在env运行时，会依次读取环境中的role信息，默认按照声明 role 的顺序依次执行 role 的 run 方法
    timestamp: int = 0

    def publish_message(self, message: Message, add_timestamp: bool = True):
        """向当前环境发布信息
        Post information to the current environment
        """
        # self.message_queue.put(message)
        if add_timestamp:
            # 一个unique的time_stamp以使得相同的message在加入记忆时不被自动去重
            message.content = f"{self.timestamp} | " + message.content
        self.memory.add(message)
        self.history += f"\n{message}"

        # 推送消息到 WebSocket 客户端
        try:
            from werewolf_game.server import broadcast
            
            broadcast(message)
        except Exception:
            pass  

    async def run(self, k=1):
        """处理一次(k=1即为一次)所有信息的运行，单协程保证各角色顺序执行（await 只是让出给系统：不会让其他角色插队）
        Process all Role runs at once
        """
        msgs = []
        for _ in range(k):
            for role in self.roles.values():
                msg = await role.run()
                msgs.append(msg)
            self.timestamp += 1
        # print("测试：",msgs)


class WerewolfGame(SoftwareCompany):
    """Use the "software company paradigm" to hold a werewolf game"""

    environment = WerewolfEnvironment()

    def start_project(self, idea):
        """Start a project from user instruction."""
        self.idea = idea
        self.environment.publish_message(
            Message(
                role="User",
                content=idea,
                cause_by=UserRequirement,
                restricted_to="Moderator",
            )
        )
