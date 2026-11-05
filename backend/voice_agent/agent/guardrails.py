"""Deterministic checks on what the caller says and what Carrie says.

They complement the model rather than replace it: patterns catch the clear
cases reliably and without a model call, the instructions cover paraphrases.
What a caller may see or change is enforced separately, in the tools.

Patterns cover English and German. Adapted from the v1 prototype.
"""

import re
from dataclasses import dataclass
from typing import Literal

from voice_agent.agent.state import CallState
from voice_agent.agent.templates import template

# --- Danger reported by the caller ---------------------------------------------

# Words that turn "smoke" into "no smoke" when they come shortly before
_NEGATION = re.compile(
    r"\b(kein\w*|nicht|ohne|nie|no|not|without|never|isn't|aren't|don't|"
    r"doesn't|didn't|there's\s+no|nothing)\b(\W+\w+){0,2}\W*$",
    re.IGNORECASE,
)
# A negation reaches no further than its clause: "kein Problem, aber Rauch"
_NEGATION_BOUNDARY = re.compile(
    r"[,;:.!?–]|\b(?:aber|doch|jedoch|sondern|trotzdem|allerdings|nur|but|however)\b",
    re.IGNORECASE,
)
# Figures of speech that sound like danger but mean urgency or anger
_FIGURES_OF_SPEECH = re.compile(
    r"\b((die\s+)?hütte\s+brennt|brennt\s+(\w+\s+)?(die|der)\s+(hütte|luft|kittel)|"
    r"brenn\w*\s+(\w+\s+){0,2}unter\s+den\s+nägeln|brenn\w*\s+darauf|"
    r"feuer\s+und\s+flamme|(geld|zeit)\s+(\w+\s+)?verbrannt|"
    r"burning\s+(question|issue|desire)|fire\s+away|under\s+fire|"
    r"(get|got|be|been)\s+fired|on\s+fire\s+(today|lately)|smoking\s+gun|"
    r"burn(ed|t)?\s+(money|cash|time))\b",
    re.IGNORECASE,
)
_DANGER = re.compile(
    r"\b(smoke|smoking|smoky|sparks?|sparking|flames?|fire|on\s+fire|"
    r"burning(\s+smell)?|smells?\s+(of\s+)?burn\w*|"
    r"overheat\w*|dangerously\s+hot|too\s+hot\s+to\s+touch|melt\w*|"
    r"electric(al)?\s+shock|"
    r"rauch\w*|qualm\w*|brenn\w*|brandgeruch|feuer\w*|flamme\w*|funken\w*|"
    r"stromschlag\w*|schmor\w*|verschmort\w*|überhitz\w*|zu\s+heiß|"
    r"geschmolzen\w*)\b",
    re.IGNORECASE,
)


def _positive_mention(pattern: re.Pattern[str], text: str) -> bool:
    """Whether the pattern occurs at least once without a negation before it.

    A negation also covers a list: "no smoke, sparks or heat".
    """
    previous_end = 0
    negated_list = False
    for match in pattern.finditer(text):
        clause = _NEGATION_BOUNDARY.split(text[: match.start()])[-1]
        between = text[previous_end : match.start()]
        continuation = re.fullmatch(
            r"[\s,]*(?:(?:and|or|nor|und|oder|noch)\s+)?(?:(?:no|kein\w*|strong|"
            r"unusual|dangerous|starke[nr]?|gefährliche[nr]?)\s+)?",
            between,
            re.IGNORECASE,
        )
        negated = bool(_NEGATION.search(clause)) or (
            negated_list and continuation is not None
        )
        if not negated:
            return True
        previous_end = match.end()
        negated_list = negated
    return False


def mentions_danger(text: str) -> bool:
    """Whether the caller reports smoke, fire, sparks, burning or overheating."""
    return _positive_mention(_DANGER, _FIGURES_OF_SPEECH.sub(",", text))


_GERMAN_DANGER = re.compile(
    r"\b(rauch\w*|qualm\w*|brenn\w*|brandgeruch|feuer\w*|flamme\w*|funken\w*|"
    r"stromschlag\w*|schmor\w*|verschmort\w*|überhitz\w*|zu\s+heiß|geschmolzen\w*)\b",
    re.IGNORECASE,
)


def safety_language(text: str, current: str, supported: tuple[str, ...]) -> str:
    """The language for the safety guidance: the one the danger was reported in.

    A German caller's first words may report smoke before the conversation
    has switched to German; the guidance must not wait for that.
    """
    words = _FIGURES_OF_SPEECH.sub(",", text)
    if "de" in supported and _positive_mention(_GERMAN_DANGER, words):
        return "de"
    if current != "en" and not _positive_mention(_GERMAN_DANGER, words):
        return "en"
    return current


# --- Payment data -----------------------------------------------------------------

_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_IBAN = re.compile(
    r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b", re.IGNORECASE
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def redact_payment_data(text: str) -> str:
    """Removes card and bank account numbers before they're stored or sent on."""

    def card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        return "[card number removed]" if _luhn_valid(digits) else match.group()

    redacted = _CARD_CANDIDATE.sub(card, text)
    return _IBAN.sub("[bank account number removed]", redacted)


# --- Carrie's replies ------------------------------------------------------------

Violation = Literal[
    "commitment",
    "safety_assurance",
    "ticket_claim",
    "transfer_claim",
    "emergency_claim",
    "unknown_reference",
    "unsafe_instruction",
]


def _patterns(*patterns: str) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


# Commitments only a person may make
_COMMITMENTS = _patterns(
    r"\b(?:I|we)(?:'ll|\s+will|\s+can)?\s+(?:guarantee|promise|refund|reimburse|"
    r"pay\s+for|cover\s+(?:the\s+)?costs?)\b",
    r"\byou(?:'ll|\s+will)\s+(?:get|receive|be\s+given|have)\s+(?:a\s+|your\s+|the\s+)?"
    r"(?:full\s+)?(?:refund|replacement\s+car|rental\s+car|loan\s+car|courtesy\s+car|"
    r"compensation|reimbursement|money\s+back)\b",
    r"\b(?:refund|compensation|claim|goodwill|reimbursement|cost\s+coverage)\s+"
    r"(?:is|has\s+been|was|will\s+be)\s+(?:approved|granted|accepted)\b",
    r"\b(?:this|it|that|the\s+repair)\s+(?:is|will\s+be)\s+(?:fully\s+)?covered\s+"
    r"(?:by|under)\s+(?:the\s+|your\s+)?warranty\b",
    r"\b(?:delivery|date)\s+is\s+(?:guaranteed|binding)\b",
    r"\b(wir|ich)\s+(übernehme\w*|erstatte\w*|ersetze\w*|bezahle\w*|zahle\w*|"
    r"schreibe\w*\s+gut)\b",
    r"\bkosten\w*\s+(werden|wird)\s+(\w+\s+)?(übernommen|erstattet)",
    r"\b((erhalten|bekommen)\s+sie|sie\s+(erhalten|bekommen))\s+(\w+\s+){0,2}"
    r"(erstattung|rückerstattung|entschädigung|gutschrift|mietwagen|ersatzwagen|"
    r"ersatzfahrzeug|leihwagen|geld\s+zurück)",
    r"\b(garantiere|verspreche|sichere\s+ihnen\s+zu)\b",
    r"\b(garantie|gewährleistung|kulanz)\w*\s+(\w+\s+){0,2}"
    r"(übernimmt|abgedeckt|gedeckt|anerkannt|genehmigt)",
    r"\bverbindliche[nr]?\s+(liefer)?termin\s+(ist|wird|steht)",
    r"\b(erstattung|entschädigung|kostenübernahme|antrag|reklamation)\w*\s+(ist|wird|"
    r"wurde)\s+(\w+\s+)?(genehmigt|bewilligt|zugesagt|anerkannt)\b",
)
_SAFETY_ASSURANCES = _patterns(
    r"\b(?:vehicle|car|battery|charger|cable|connector|it)\s+is\s+"
    r"(?:completely\s+|perfectly\s+|totally\s+)?safe\b",
    r"\b(?:you\s+can|it's\s+safe\s+to)\s+(?:safely\s+)?(?:keep|continue)\s+"
    r"(?:driving|charging)\b",
    r"\bthere(?:'s|\s+is)\s+no\s+(?:danger|risk)\b",
    r"\b(können|dürfen)\s+(\w+\s+)?(problemlos|bedenkenlos|gefahrlos|unbesorgt)\s+"
    r"(weiter)?(fahren|laden)",
    r"\b(ist|sind)\s+(völlig\s+|absolut\s+)?(ungefährlich|unbedenklich)",
    r"\bbesteht\s+keine\s+gefahr\b",
)
_TICKET_CLAIMS = _patterns(
    r"\b(?:I|we)(?:'ve|\s+have)\s+(?:just\s+|now\s+)?(?:created|opened|logged|"
    r"registered|filed|added|updated)\b.{0,40}\b(?:ticket|case|note|request)\b",
    r"\b(?:ticket|case|note)\s+(?:has\s+been|was|is\s+now)\s+(?:created|opened|"
    r"logged|added|updated|registered)\b",
    r"\b(?:ich\s+habe|wir\s+haben)\b.{0,50}\b(?:ticket|vorgang|anfrage|notiz|fall)\b"
    r".{0,30}\b(?:angelegt|erstellt|erfasst|aufgenommen|ergänzt|hinzugefügt)\b",
    r"\b(?:ticket|vorgang|notiz|anfrage)\s+(?:ist|wurde)\s+(?:jetzt\s+)?(?:angelegt|"
    r"erstellt|erfasst|ergänzt)\b",
)
_TRANSFER_CLAIMS = _patterns(
    r"\b(?:I(?:'ve|\s+have)\s+(?:transferred|connected|forwarded|put)\s+you|"
    r"you(?:'re|\s+are)\s+(?:now\s+)?(?:being\s+)?(?:connected|transferred|put\s+through)|"
    r"(?:I'm|I\s+am)\s+(?:now\s+)?(?:connecting|transferring|putting)\s+you)\b",
    r"\b(?:ich\s+verbinde\s+sie|die\s+verbindung\s+steht|ich\s+habe\s+sie\s+"
    r"(?:weiter|ver)\w*|ich\s+leite\s+sie\s+(?:jetzt\s+)?weiter|"
    r"ich\s+übergebe\s+sie|sie\s+werden\s+(?:jetzt\s+)?(?:verbunden|weitergeleitet))\b",
)
_EMERGENCY_CLAIMS = _patterns(
    r"\b(?:I|we)(?:'ve|\s+have)\s+(?:called|notified|alerted|contacted|informed)\s+"
    r"(?:the\s+)?(?:fire|emergency|police|ambulance|112)",
    r"\b(?:ich\s+habe|wir\s+haben)\s+(?:die\s+|den\s+)?(?:feuerwehr|notruf|polizei|"
    r"rettung\w*)\s+(?:verständigt|alarmiert|gerufen|informiert)",
)
_UNSAFE_INSTRUCTIONS = _patterns(
    r"\b(?:open|remove|bypass|repair|touch|unplug)\b.{0,45}\b(?:enclosure|high.voltage|"
    r"interlock|damaged\s+cable)\b",
    r"\b(?:force|forcibly|yank|pull\s+hard)\b.{0,25}\b(?:connector|plug|cable)\b",
    r"\b(?:öffnen|öffne|umgehen|überbrücken|reparieren|berühren)\b.{0,45}"
    r"\b(?:gehäuse|hochvolt|verriegelung|beschädigte\w*\s+kabel)\b",
    r"\b(?:mit\s+gewalt|gewaltsam|kräftig\s+ziehen)\b",
)
_REFERENCE = re.compile(r"\bCC[-\s]?(\d{5})\b", re.IGNORECASE)
_CLAUSE = re.compile(
    r"[,;:–]|\b(aber|jedoch|sondern|dass|ob|but|whether|if|wenn|falls)\b",
    re.IGNORECASE,
)
_CLAUSE_NEGATION = re.compile(
    r"\b(nicht|nichts|kein\w*|nie|not|no|never|cannot|can't|won't|don't|"
    r"isn't|unable)\b",
    re.IGNORECASE,
)
# Questions and offers aren't claims: "Shall I create a ticket?"
_QUESTION = re.compile(r"\?\s*$")


def check_reply(sentence: str, state: CallState) -> Violation | None:
    """A statement Carrie must not make in this sentence, if any."""
    for number in _REFERENCE.findall(sentence):
        if state.ticket(f"CC-{number}") is None:
            return "unknown_reference"
    if any(p.search(sentence) for p in _SAFETY_ASSURANCES):
        return "safety_assurance"
    if any(p.search(sentence) for p in _EMERGENCY_CLAIMS):
        return "emergency_claim"
    if _QUESTION.search(sentence):
        return None
    for clause in _CLAUSE.split(sentence):
        if not clause or _CLAUSE_NEGATION.search(clause):
            continue
        if any(p.search(clause) for p in _UNSAFE_INSTRUCTIONS):
            return "unsafe_instruction"
        if any(p.search(clause) for p in _COMMITMENTS):
            return "commitment"
        if not state.tickets_changed and any(p.search(clause) for p in _TICKET_CLAIMS):
            return "ticket_claim"
        if not state.transferred and any(p.search(clause) for p in _TRANSFER_CLAIMS):
            return "transfer_claim"
    return None


@dataclass(frozen=True)
class Checked:
    """A reply sentence after the check: what to say instead, if anything."""

    text: str | None
    violation: Violation | None


def guard(sentence: str, state: CallState) -> Checked:
    """The sentence, a safe replacement, or None to leave it out."""
    violation = check_reply(sentence, state)
    match violation:
        case None:
            return Checked(sentence, None)
        case "commitment":
            return Checked(template("withheld", state.language), violation)
        case "safety_assurance":
            return Checked(template("safety_unconfirmed", state.language), violation)
        case _:
            # Premature or made-up claims: the tool result follows anyway
            return Checked(None, violation)
