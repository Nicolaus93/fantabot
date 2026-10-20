from copy import deepcopy
from unittest.mock import Mock

import pytest

from fantabot.telegram import GroupMessage, addressed_message, send_reply

GROUP_ID = -100123
BOT_ID = 123456
BOT_USERNAME = "Fantabot"


def update(text="/ask Chi schiero?", **message_overrides):
    message = {
        "chat": {"id": GROUP_ID, "type": "supergroup"},
        "from": {"id": 42, "is_bot": False},
        "message_id": 10,
        "text": text,
    }
    message.update(message_overrides)
    return {"update_id": 100, "message": message}


def route(payload):
    return addressed_message(payload, GROUP_ID, BOT_USERNAME, BOT_ID)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/ask Chi schiero?", "Chi schiero?"),
        ("/ask@Fantabot Chi schiero?", "Chi schiero?"),
        ("/ASK@FANTABOT Chi schiero?", "Chi schiero?"),
        ("Ciao @Fantabot!", "Ciao !"),
        ("@fantabot Chi schiero?", "Chi schiero?"),
        ("/ask", ""),
    ],
)
def test_explicit_addresses_are_routed(text, expected):
    message = route(update(text))
    assert message.text == expected
    assert message.chat_id == GROUP_ID
    assert message.user_id == 42
    assert message.message_id == 10


@pytest.mark.parametrize("text", ["/classifica", "/classifica@Fantabot", "/CLASSIFICA@FANTABOT"])
def test_standings_command_is_routed_separately(text):
    message = route(update(text, message_thread_id=2))
    assert message.command == "classifica"
    assert message.text == ""
    assert message.thread_id == 2


def test_ask_text_does_not_become_a_standings_command():
    message = route(update("/ask /classifica"))
    assert message.command == "ask"
    assert message.text == "/classifica"


def test_reply_to_this_bot_is_routed_without_mention():
    message = route(update("E invece lui?", reply_to_message={"from": {"id": BOT_ID}}))
    assert message.text == "E invece lui?"


@pytest.mark.parametrize(
    "payload",
    [
        update("Conversazione normale"),
        update("/ask@OtherBot Chi schiero?"),
        update("/start"),
        update("/askmore domanda"),
        update("/classifica@OtherBot"),
        update("/classificamore"),
        update("@Fantabot_extra Chi schiero?"),
        update("Risposta", reply_to_message={"from": {"id": BOT_ID + 1}}),
        update(chat={"id": GROUP_ID - 1, "type": "supergroup"}),
        update(chat={"id": GROUP_ID, "type": "private"}),
        update(**{"from": {"id": 42, "is_bot": True}}),
        {"update_id": 100, "edited_message": update()["message"]},
        {"update_id": 100, "channel_post": update()["message"]},
        update(text=None),
        update(message_id=True),
        update(message_thread_id="not-a-topic"),
        {"update_id": True, "message": update()["message"]},
        None,
        [],
    ],
)
def test_unaddressed_or_untrusted_updates_are_ignored(payload):
    assert route(payload) is None


def test_other_commands_targeted_at_this_bot_are_ignored():
    assert route(update("/help@Fantabot")) is None


def test_topics_have_distinct_shared_conversation_ids():
    base = route(update())
    topic_one = route(update(message_thread_id=1))
    topic_two = route(update(message_thread_id=2))
    assert len({base.conversation_id, topic_one.conversation_id, topic_two.conversation_id}) == 3
    same_topic = deepcopy(update(message_thread_id=1))
    same_topic["message"]["from"]["id"] = 99
    assert route(same_topic).conversation_id == topic_one.conversation_id


def test_reply_is_plain_text_in_correct_topic_and_bounded():
    client = Mock()
    client.post.return_value.json.return_value = {"ok": True}
    message = GroupMessage(1, GROUP_ID, 42, 10, 2, "question")
    text = "_*[ciao]*_" + "x" * 5000
    send_reply(client, "fake-token", message, text)
    args, kwargs = client.post.call_args
    assert args[0] == "https://api.telegram.org/botfake-token/sendMessage"
    payload = kwargs["json"]
    assert payload["text"] == text[:4000]
    assert "parse_mode" not in payload
    assert payload["message_thread_id"] == 2
    assert payload["reply_parameters"]["message_id"] == 10
    client.post.return_value.raise_for_status.assert_called_once()


def test_reply_without_topic_omits_thread():
    client = Mock()
    client.post.return_value.json.return_value = {"ok": True}
    send_reply(client, "fake-token", GroupMessage(1, GROUP_ID, 42, 10, None, "q"), "ciao")
    assert "message_thread_id" not in client.post.call_args.kwargs["json"]


def test_telegram_rejection_is_not_silently_accepted():
    client = Mock()
    client.post.return_value.json.return_value = {"ok": False}
    with pytest.raises(RuntimeError, match="Telegram rejected"):
        send_reply(client, "fake-token", GroupMessage(1, GROUP_ID, 42, 10, None, "q"), "ciao")
