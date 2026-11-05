"""Reply text as it should be read aloud."""

import re

_URL = re.compile(r"https?://\S+")
# Markdown emphasis, headings, code and list markers
_MARKUP = re.compile(r"[*_#`>~|]+")
# Pictographs, dingbats and other symbols a voice can't read
_SYMBOLS = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0000fe0f\U0000200d]+"
)
_WHITESPACE = re.compile(r"\s+")


def speakable(text: str) -> str:
    text = _URL.sub("the link", text)
    text = _MARKUP.sub(" ", text)
    text = _SYMBOLS.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


# Words a period doesn't end a sentence after (compared in lower case)
ABBREVIATIONS = frozenset(
    {
        "mr.",
        "mrs.",
        "ms.",
        "dr.",
        "prof.",
        "st.",
        "jr.",
        "sr.",
        "vs.",
        "etc.",
        "e.g.",
        "i.e.",
        "approx.",
        "no.",
        "dept.",
        "inc.",
        "ltd.",
        "co.",
        # German
        "nr.",
        "ca.",
        "bzw.",
        "str.",
        "usw.",
        "evtl.",
        "ggf.",
        "inkl.",
        "zzgl.",
        "tel.",
    }
)
# A sentence end: punctuation, optional closing quotes or brackets, whitespace
_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*\s+|\n+")


def _ends_with_abbreviation(sentence: str) -> bool:
    words = sentence.split()
    if not words:
        return False
    last = words[-1].lower().lstrip("\"'([")
    # Single letters are initials, as in "J. R. R. Tolkien" or "U.S." (and
    # German "z. B."); one or two digits are a German ordinal ("am 10. November")
    return last in ABBREVIATIONS or bool(re.fullmatch(r"([a-zäöü]\.)+|\d{1,2}\.", last))


class SentenceBuffer:
    """Collects streamed text and hands out complete sentences, for speech.

    A sentence ends at ., ! or ? followed by whitespace, or at a line break,
    except after common English and German abbreviations, initials, and
    German ordinals ("10. November"). Decimals ("3.5") have no whitespace
    after the period, so they never split.
    """

    def __init__(self) -> None:
        self._text = ""

    def push(self, delta: str) -> list[str]:
        self._text += delta
        sentences: list[str] = []
        start = 0
        for match in _SENTENCE_END.finditer(self._text):
            candidate = self._text[start : match.end()].strip()
            if match.group().strip() and _ends_with_abbreviation(
                self._text[start : match.start() + 1]
            ):
                continue
            if candidate:
                sentences.append(candidate)
            start = match.end()
        self._text = self._text[start:]
        return sentences

    def flush(self) -> str | None:
        """The rest, once the text is complete."""
        rest, self._text = self._text.strip(), ""
        return rest or None
