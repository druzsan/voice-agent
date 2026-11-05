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
