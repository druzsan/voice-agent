import pytest

from voice_agent.conversation.text import speakable


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("**Sure!** Here you go.", "Sure! Here you go."),
        ("# Title\n- one\n- two", "Title - one - two"),
        ("See https://example.com/docs for more.", "See the link for more."),
        ("Great news 🎉👍 really", "Great news really"),
        ("It's 3.5 km away.", "It's 3.5 km away."),
    ],
)
def test_speakable_drops_what_a_voice_cant_read(text: str, spoken: str) -> None:
    assert speakable(text) == spoken
