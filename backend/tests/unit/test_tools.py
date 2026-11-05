"""Carrie's tools against the seeded in-memory customer care system."""

from types import SimpleNamespace
from typing import cast

import pytest
from pydantic_ai import RunContext

from tests.fakes import call_deps
from voice_agent.agent.deps import CallDeps
from voice_agent.agent.state import CallState
from voice_agent.agent.tools import (
    add_ticket_note,
    create_ticket,
    find_open_tickets,
    handover_to_human,
    lookup_order,
    set_language,
)
from voice_agent.crm.memory import InMemoryCrm

pytestmark = pytest.mark.anyio


def context(deps: CallDeps) -> RunContext[CallDeps]:
    # The tools only use the dependencies
    return cast(RunContext[CallDeps], SimpleNamespace(deps=deps))


# --- lookup_order -----------------------------------------------------------------


async def test_an_order_is_disclosed_after_all_four_details_match() -> None:
    deps = call_deps()

    result = await lookup_order(
        context(deps), "4 5 6 7 8 9", "Jana Mueller", "10115", "iX3"
    )

    assert result["status"] == "verified"
    assert "confirmed_delivery_date" in result["order"]
    assert deps.state.verified_orders[0].order_number == "456789"
    assert [e.label for e in deps.events] == ["Order 456789 verified"]


async def test_missing_details_are_named_without_a_lookup() -> None:
    deps = call_deps()

    result = await lookup_order(context(deps), "456789", "", "10115", "")

    assert result == {
        "status": "incomplete",
        "missing": ["customer_name", "vehicle_model"],
        "instruction": "Ask the caller for the next missing detail.",
    }
    assert deps.state.failed_order_lookups == 0


async def test_a_mismatch_doesnt_say_which_detail_was_wrong() -> None:
    deps = call_deps()

    result = await lookup_order(context(deps), "456789", "Jana Müller", "10117", "iX3")

    assert result["status"] == "no_match"
    assert "order" not in result
    assert "10115" not in str(result)
    assert deps.state.verified_orders == []


async def test_two_failures_lock_the_order_lookup() -> None:
    deps = call_deps()
    for _ in range(2):
        await lookup_order(context(deps), "456789", "Someone Else", "10115", "iX3")

    # Even the right details don't help any more in this call
    result = await lookup_order(context(deps), "456789", "Jana Müller", "10115", "iX3")

    assert result["status"] == "locked"


async def test_a_missed_estimate_with_a_new_one_is_reported_as_an_estimate() -> None:
    deps = call_deps()

    result = await lookup_order(context(deps), "527713", "Katrin Weber", "50667", "X5")

    order = result["order"]
    assert "estimate, not confirmed" in order["estimated_delivery_window"]
    assert "previous_estimate" in order
    assert order["reason_for_change"] == "none recorded"
    assert "confirmed_delivery_date" not in order


async def test_a_stale_status_carries_a_warning() -> None:
    deps = call_deps()

    result = await lookup_order(
        context(deps), "610938", "Lukas Fischer", "70173", "330e Touring"
    )

    warning = result["order"]["reliability_warning"]
    assert "outdated" in warning and "already passed" in warning


# --- Tickets ----------------------------------------------------------------------


async def test_open_tickets_are_found_by_the_caller_number_and_last_name() -> None:
    deps = call_deps(CallState(caller_phone="+4915122000201"))

    result = await find_open_tickets(context(deps), "Hoffmann")

    assert result["status"] == "found"
    assert [t["reference"] for t in result["open_tickets"]] == ["CC-10006"]
    assert deps.state.ticket("CC-10006") is not None


async def test_closed_tickets_are_counted_but_not_shown() -> None:
    deps = call_deps()

    result = await find_open_tickets(
        context(deps), "Wagner", ticket_reference="C C 1 0 0 0 8"
    )

    assert result["status"] == "none_open"
    assert result["open_tickets"] == [] and result["closed_tickets"] == 1


async def test_a_ticket_of_someone_else_isnt_found() -> None:
    deps = call_deps()

    result = await find_open_tickets(
        context(deps), "Müller", ticket_reference="CC-10006"
    )

    assert result["status"] == "not_found"
    assert deps.state.failed_ticket_lookups == 1


async def test_a_note_needs_a_ticket_found_in_this_call() -> None:
    crm = InMemoryCrm.seeded()
    deps = call_deps(crm=crm)

    refused = await add_ticket_note(context(deps), "CC-10006", "Still broken.")
    await find_open_tickets(context(deps), "Hoffmann", order_number="318842")
    added = await add_ticket_note(
        context(deps), "CC-10006", "Stopped twice yesterday, card 4111 1111 1111 1111."
    )

    assert refused["status"] == "not_allowed"
    assert added["status"] == "added"
    note = crm.notes[10006][-1]
    assert note.author == "carrie"
    assert "4111" not in note.body


async def test_a_note_reopens_a_ticket_waiting_on_the_customer() -> None:
    crm = InMemoryCrm.seeded()
    deps = call_deps(CallState(caller_phone="+4915122000105"), crm)
    await find_open_tickets(context(deps), "Becker")

    result = await add_ticket_note(
        context(deps), "CC-10005", "Dealer confirmation sent.", raise_priority_to="high"
    )

    assert (result["ticket_status"], result["priority"]) == ("open", "high")


async def test_a_ticket_needs_an_order_number() -> None:
    deps = call_deps()

    result = await create_ticket(
        context(deps), "connected_services", "login", "App sign-in fails.", ""
    )

    assert result["status"] == "missing"
    assert result["missing"] == ["order_number"]


async def test_a_ticket_uses_the_caller_number_and_marks_verification() -> None:
    crm = InMemoryCrm.seeded()
    deps = call_deps(crm=crm)
    await lookup_order(context(deps), "527713", "Katrin Weber", "50667", "X5")

    result = await create_ticket(
        context(deps),
        "delivery",
        "delivery_delay",
        "Wants a replacement car from tomorrow.",
        "527713",
        priority="high",
        details={"lease_end": "tomorrow"},
    )

    ticket = crm.tickets[int(result["ticket"][3:])]
    assert result["status"] == "created"
    assert ticket.mobile_phone == "+4915199990000"
    assert ticket.verification_status == "order_verified"
    assert ticket.customer_id is not None
    # One ticket per topic and call
    again = await create_ticket(context(deps), "delivery", "x", "Again.", "527713")
    assert again["status"] == "exists"


# --- Transfers and language ---------------------------------------------------------


async def test_a_transfer_needs_no_customer_data_and_puts_the_call_on_hold() -> None:
    crm = InMemoryCrm.seeded()
    deps = call_deps(CallState(language="de"), crm)

    result = await handover_to_human(
        context(deps),
        "technical_support",
        "Caller wants a person",
        "App-Anmeldung schlägt seit heute fehl.",
    )

    assert result["status"] == "transferred"
    assert deps.state.hold_requested
    handover = crm.handovers[0]
    assert handover.language == "de"
    assert handover.summary.startswith("Language: German.")


async def test_an_unavailable_route_says_so() -> None:
    deps = call_deps(unavailable=frozenset({"roadside_assistance"}))

    result = await handover_to_human(
        context(deps), "roadside_assistance", "Stranded", "Battery at 4 percent."
    )

    assert result["status"] == "unavailable"
    assert not deps.state.hold_requested
    assert deps.events[-1].status == "failed"


async def test_only_supported_languages_can_be_set() -> None:
    deps = call_deps(languages=("en",))

    refused = await set_language(context(deps), "de")
    accepted = await set_language(context(deps), "en")

    assert refused["status"] == "unsupported"
    assert "language_support" in refused["instruction"]
    assert accepted["status"] == "ok"
    assert deps.state.language == "en"
