import pytest

from voice_agent.agent.guardrails import (
    check_reply,
    guard,
    mentions_danger,
    redact_payment_data,
    safety_language,
)
from voice_agent.agent.state import CallHandover, CallState, CallTicket
from voice_agent.agent.templates import template


@pytest.mark.parametrize(
    "said",
    [
        "There's smoke coming out of the charging port!",
        "I can see sparks at the charger",
        "Es riecht stark verbrannt und qualmt",
        "Aus dem Ladeanschluss kommt Rauch!",
        "The cable is melting",
        "Das Kabel ist überhitzt",
        "No error, but now there's smoke",
        "kein Fehler, aber Funken",
    ],
)
def test_danger_is_recognized(said: str) -> None:
    assert mentions_danger(said)


@pytest.mark.parametrize(
    "said",
    [
        "No, there's no smoke, sparks or heat.",
        "Nein, kein Rauch, keine Funken und keine Hitze.",
        "There is no smoke or burning smell",
        "Bei uns brennt die Hütte, ich brauche das Auto!",
        "That's a burning question for me",
        "My delivery is late again",
        "Es gibt keinen Brandgeruch",
    ],
)
def test_negations_and_figures_of_speech_arent_danger(said: str) -> None:
    assert not mentions_danger(said)


def test_card_and_bank_numbers_are_removed() -> None:
    text = "My card is 4111 1111 1111 1111 and IBAN DE89 3704 0044 0532 0130 00."

    redacted = redact_payment_data(text)

    assert "4111" not in redacted and "DE89" not in redacted
    assert "[card number removed]" in redacted
    assert "[bank account number removed]" in redacted


def test_order_and_phone_numbers_stay() -> None:
    text = "Order 456789, call me on 0151 22000201"

    assert redact_payment_data(text) == text


@pytest.mark.parametrize(
    "reply",
    [
        "You'll get a rental car until your delivery arrives.",
        "We will cover the costs of the rental car.",
        "Your refund has been approved.",
        "Die Kosten werden übernommen.",
        "Sie bekommen einen Mietwagen.",
        "This is covered by your warranty.",
    ],
)
def test_commitments_are_withheld(reply: str) -> None:
    state = CallState()

    assert check_reply(reply, state) == "commitment"
    assert guard(reply, state).text == template("withheld", "en")


@pytest.mark.parametrize(
    "reply",
    [
        "I can't promise a rental car; the delivery team decides.",
        "Shall I create a ticket for this?",
        "I'll request the transfer now.",
        "Your delivery is confirmed for Tuesday, 10 November.",
        "I've noted that you called twice.",
        "Ich kann Ihnen keinen Mietwagen zusagen.",
    ],
)
def test_ordinary_replies_pass(reply: str) -> None:
    assert check_reply(reply, CallState()) is None


def test_a_ticket_claim_needs_a_ticket() -> None:
    claim = "I've created a ticket for the delivery team."
    state = CallState()

    assert check_reply(claim, state) == "ticket_claim"
    assert guard(claim, state).text is None

    state.tickets.append(
        CallTicket(
            reference="CC-10021",
            topic="delivery",
            status="open",
            origin="created",
            summary="Late delivery",
        )
    )
    assert check_reply(claim, state) is None


def test_a_transfer_claim_needs_a_transfer() -> None:
    claim = "I'm connecting you with technical support now."
    state = CallState()

    assert check_reply(claim, state) == "transfer_claim"
    state.handovers.append(
        CallHandover(route="technical_support", status="transferred")
    )
    assert check_reply(claim, state) is None


def test_only_known_ticket_references_are_spoken() -> None:
    state = CallState()

    assert check_reply("Your ticket is CC-12345.", state) == "unknown_reference"


@pytest.mark.parametrize(
    ("reply", "violation"),
    [
        ("The car is safe to drive.", "safety_assurance"),
        ("Es besteht keine Gefahr.", "safety_assurance"),
        ("I've called the fire department for you.", "emergency_claim"),
        ("Just pull hard on the connector to force it out.", "unsafe_instruction"),
    ],
)
def test_safety_statements_are_caught(reply: str, violation: str) -> None:
    assert check_reply(reply, CallState()) == violation


def test_replacements_are_in_the_conversation_language() -> None:
    state = CallState(language="de")

    assert guard("Sie bekommen einen Mietwagen.", state).text == template(
        "withheld", "de"
    )


def test_safety_guidance_follows_the_language_of_the_report() -> None:
    both = ("en", "de")

    assert safety_language("Aus dem Ladeanschluss kommt Rauch!", "en", both) == "de"
    assert safety_language("There's smoke at the charger!", "de", both) == "en"
    assert safety_language("Rauch!", "en", ("en",)) == "en"
