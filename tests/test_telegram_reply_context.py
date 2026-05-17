from app.bot.telegram import message_with_reply_context, reply_context_text, task_with_reply_context


class FakeReply:
    def __init__(self, text: str = "", caption: str = ""):
        self.text = text
        self.caption = caption


class FakeMessage:
    def __init__(self, text: str, reply=None):
        self.text = text
        self.reply_to_message = reply


def test_message_with_reply_context_includes_replied_text():
    message = FakeMessage("search this", FakeReply(text="Where does ChatGPT macOS store conversations?"))

    rendered = message_with_reply_context(message)

    assert "User message:\nsearch this" in rendered
    assert "Telegram reply context:\nWhere does ChatGPT macOS store conversations?" in rendered


def test_task_with_reply_context_includes_replied_text():
    message = FakeMessage("search this", FakeReply(text="Find current ChatGPT export docs"))

    rendered = task_with_reply_context("search this", message)

    assert "User task:\nsearch this" in rendered
    assert "Telegram reply context:\nFind current ChatGPT export docs" in rendered


def test_reply_context_uses_caption_fallback():
    message = FakeMessage("search this", FakeReply(caption="Screenshot caption"))

    assert reply_context_text(message) == "Screenshot caption"


def test_message_without_reply_stays_plain():
    assert message_with_reply_context(FakeMessage("search this")) == "search this"
