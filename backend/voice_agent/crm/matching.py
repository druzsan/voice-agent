"""Comparing what a caller says with what the system has stored.

Identity checks are exact after normalization: names lose case, titles and
accents (Müller = Mueller = Muller), numbers lose spaces and spoken digit
words. Only the vehicle model is matched loosely, since it isn't a secret.
"""

import re
import unicodedata

_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "null": "0",
    "eins": "1",
    "zwei": "2",
    "zwo": "2",
    "drei": "3",
    "vier": "4",
    "fünf": "5",
    "funf": "5",
    "sechs": "6",
    "sieben": "7",
    "acht": "8",
    "neun": "9",
}
_TITLES = frozenset(
    {"herr", "frau", "mr", "mrs", "ms", "miss", "dr", "prof", "von", "der", "de"}
)
# Words in a model name that don't tell models apart
_MODEL_FILLER = frozenset(
    {"bmw", "the", "my", "a", "an", "new", "neue", "neuer", "neuen", "mein", "meinen"}
)


def _ascii_variants(text: str) -> set[str]:
    """Both German transliterations: ü → ue and ü → u."""
    lowered = text.casefold().replace("ß", "ss")
    expanded = lowered.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    stripped = "".join(
        char
        for char in unicodedata.normalize("NFKD", lowered)
        if not unicodedata.combining(char)
    )
    return {expanded, stripped}


def _name_tokens(name: str) -> list[str]:
    tokens = re.findall(r"[^\W\d_]+", name.casefold())
    return [token for token in tokens if token not in _TITLES]


def _token_forms(token: str) -> set[str]:
    forms = _ascii_variants(token)
    # "Mueller" spoken or typed for "Müller": also compare its plain form
    for form in list(forms):
        forms.add(form.replace("ae", "a").replace("oe", "o").replace("ue", "u"))
    return forms


def same_word(said: str, stored: str) -> bool:
    return bool(_token_forms(said) & _token_forms(stored))


def name_matches(said: str, first_name: str, last_name: str) -> bool:
    """The caller's name against the stored one.

    The last name must be there; a first name, if given, must match too.
    Titles ("Frau Dr.") don't count.
    """
    tokens = _name_tokens(said)
    last = _name_tokens(last_name)
    first = _name_tokens(first_name)
    if not tokens or not last or len(tokens) < len(last):
        return False
    said_last, said_first = tokens[-len(last) :], tokens[: -len(last)]
    if not all(same_word(a, b) for a, b in zip(said_last, last, strict=True)):
        return False
    if not said_first:
        return True
    return len(said_first) <= len(first) and all(
        same_word(a, b) for a, b in zip(said_first, first, strict=False)
    )


def last_name_matches(said: str, last_name: str) -> bool:
    """Only the last name: the caller may say their full name."""
    tokens = _name_tokens(said)
    last = _name_tokens(last_name)
    if not tokens or not last or len(tokens) < len(last):
        return False
    return all(same_word(a, b) for a, b in zip(tokens[-len(last) :], last, strict=True))


def digits(text: str) -> str:
    """The digits of a spoken or typed number: 'eins null 1 15' -> '10115'."""
    words = re.findall(r"\d+|[^\W\d_]+", text.casefold())
    return "".join(
        word if word.isdigit() else _DIGIT_WORDS.get(word, "") for word in words
    )


def normalize_phone(text: str) -> str | None:
    """A German phone number as E.164 (+49...), or None if it isn't one.

    Accepts +49, 0049 and the national 0 prefix.
    """
    plus = text.strip().startswith("+")
    number = digits(text)
    if plus and number.startswith("49"):
        national = number[2:]
    elif number.startswith("0049"):
        national = number[4:]
    elif number.startswith("0"):
        national = number[1:]
    else:
        return None
    national = national.removeprefix("0")
    if not 7 <= len(national) <= 12:
        return None
    return f"+49{national}"


def _model_tokens(model: str) -> set[str]:
    text = model.casefold().replace("-", " ")
    # "i x 3" from speech recognition, "iX 3" typed
    text = re.sub(r"\b([a-z])\s+(\d)", r"\1\2", text)
    text = re.sub(r"\bi\s+x(\d)?", lambda m: f"ix{m.group(1) or ''}", text)
    tokens = set(re.findall(r"[a-z0-9]+", text))
    return tokens - _MODEL_FILLER


_SERIES = frozenset(
    {"i3", "i4", "i5", "i7", "ix", "ix1", "ix2", "ix3", "x1", "x2", "x3", "x4"}
    | {"x5", "x6", "x7", "z4", "m3", "m4", "m5"}
)


def _distinguishing(token: str) -> bool:
    """A series or model code (X5, 330e, i4), not a word like Touring."""
    return token in _SERIES or any(char.isdigit() for char in token)


def model_matches(said: str, stored: str) -> bool:
    """Whether the caller names the stored model, loosely.

    One distinguishing token is enough ("X5" for "BMW X5 xDrive50e"), but
    another series is not: "iX" doesn't match "iX3", "Touring" alone
    matches nothing.
    """
    said_tokens = _model_tokens(said)
    stored_tokens = _model_tokens(stored)
    shared = said_tokens & stored_tokens
    other_series = (said_tokens - stored_tokens) & _SERIES
    return any(_distinguishing(token) for token in shared) and not other_series
