import pytest

from voice_agent.conversation.text import SentenceBuffer, speakable


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


def sentences(*deltas: str) -> list[str]:
    buffer = SentenceBuffer()
    found = [sentence for delta in deltas for sentence in buffer.push(delta)]
    rest = buffer.flush()
    return [*found, rest] if rest else found


def test_streamed_text_comes_out_sentence_by_sentence() -> None:
    buffer = SentenceBuffer()

    assert buffer.push("Hello there") == []
    assert buffer.push("! How are") == ["Hello there!"]
    assert buffer.push(" you? I'm") == ["How are you?"]
    assert buffer.flush() == "I'm"
    assert buffer.flush() is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mr. Smith is here. Dr. Who too.", ["Mr. Smith is here.", "Dr. Who too."]),
        ("It costs 3.50 euros. Okay?", ["It costs 3.50 euros.", "Okay?"]),
        ("Bring e.g. a pen. Thanks.", ["Bring e.g. a pen.", "Thanks."]),
        (
            "The U.S. office. J. R. R. Tolkien.",
            ["The U.S. office.", "J. R. R. Tolkien."],
        ),
        ('He said "Stop!" Then he left.', ['He said "Stop!"', "Then he left."]),
        ("Really?! Yes... Fine.", ["Really?!", "Yes...", "Fine."]),
        ("One line\nAnother line", ["One line", "Another line"]),
    ],
)
def test_sentences_end_where_english_ends_them(text: str, expected: list[str]) -> None:
    # Character by character, like the smallest stream deltas
    assert sentences(*text) == expected
    assert sentences(text) == expected
