import asyncio

from app.bot.telegram import with_typing_indicator


class FakeBot:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[int, str]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        if self.fail:
            raise RuntimeError("telegram unavailable")
        self.calls.append((chat_id, action))


class FakeChat:
    id = 123


class FakeMessage:
    def __init__(self, bot: FakeBot):
        self.bot = bot
        self.chat = FakeChat()


def test_with_typing_indicator_sends_typing_action():
    bot = FakeBot()
    message = FakeMessage(bot)

    async def operation():
        await asyncio.sleep(0)
        return "done"

    result = asyncio.run(with_typing_indicator(message, operation))

    assert result == "done"
    assert bot.calls == [(123, "typing")]


def test_with_typing_indicator_ignores_chat_action_errors():
    message = FakeMessage(FakeBot(fail=True))

    async def operation():
        return "done"

    assert asyncio.run(with_typing_indicator(message, operation)) == "done"
