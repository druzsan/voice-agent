from datetime import datetime
from zoneinfo import ZoneInfo

from voice_agent.agent.state import CallHandover, CallState, VerifiedOrder, describe

NOW = datetime(2026, 11, 5, 14, 3, tzinfo=ZoneInfo("Europe/Berlin"))


def test_the_state_block_names_time_language_and_caller() -> None:
    text = describe(CallState(caller_phone="+4915122000201"), NOW, ("en", "de"))

    assert "Thursday, 5 November 2026, 14:03" in text
    assert (
        "Conversation language: English. Supported languages: English, German." in text
    )
    assert "+4915122000201" in text
    assert "No ticket identified" in text


def test_the_state_block_restates_verified_facts() -> None:
    state = CallState(
        language="de",
        verified_orders=[
            VerifiedOrder(
                order_number="456789",
                customer_name="Jana Müller",
                facts="confirmed_delivery_date: Tuesday, 10 November 2026",
            )
        ],
        failed_ticket_lookups=1,
        emergency=True,
    )

    text = describe(state, NOW, ("en", "de"))

    assert "Conversation language: German" in text
    assert "Verified order 456789 (Jana Müller)" in text
    assert "Failed ticket identifications: 1 of 2." in text
    assert "DANGER WAS REPORTED" in text


def test_a_transfer_reads_differently_before_and_after_the_hold() -> None:
    state = CallState(
        handovers=[CallHandover(route="technical_support", status="transferred")],
        hold_requested=True,
    )

    assert "goes on hold after your reply" in describe(state, NOW, ("en",))
    state.hold_requested = False
    assert "back with you" in describe(state, NOW, ("en",))
