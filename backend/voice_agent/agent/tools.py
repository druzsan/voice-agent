"""Carrie's tools: thin, each one validates, calls the CRM and reports back.

The rules about who may see or change what are enforced here, not in the
prompt: identification, the limit on failed attempts, which tickets a call
may update. Results contain only what the next answer needs, and an
instruction when the model must act on a refusal.

Writes run shielded from cancellation: a caller talking over Carrie stops
her speech, not half a ticket.
"""

from collections.abc import Awaitable
from datetime import date, datetime, timedelta
from typing import Any

import anyio
from pydantic_ai import RunContext

from voice_agent.agent.deps import CallDeps, ToolEvent
from voice_agent.agent.guardrails import redact_payment_data
from voice_agent.agent.language import language_name
from voice_agent.agent.state import (
    MAX_FAILED_LOOKUPS,
    CallHandover,
    CallTicket,
    VerifiedOrder,
)
from voice_agent.crm.matching import (
    digits,
    last_name_matches,
    model_matches,
    name_matches,
    normalize_phone,
)
from voice_agent.crm.records import (
    OPEN_STATUSES,
    NewHandover,
    NewTicket,
    Order,
    Priority,
    Route,
    TicketDetail,
    Topic,
)

# A status older than this may be outdated
STALE_AFTER = timedelta(days=21)

_ORDER_STATUS = {
    "ordered": "ordered, not yet in production",
    "in_production": "in production",
    "in_transit": "on its way to the dealer",
    "at_dealer": "at the dealer",
    "delivered": "delivered",
}


def _day(value: date) -> str:
    return f"{value:%A}, {value.day} {value:%B %Y}"


def _window(start: date | None, end: date | None) -> str | None:
    if start is None or end is None:
        return None
    return f"{start.day} {start:%B} to {end.day} {end:%B %Y}"


def _order_facts(order: Order, today: date, now: datetime) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "model": order.model,
        "order_status": _ORDER_STATUS.get(order.status, order.status),
        "dealer": order.dealer,
        "status_last_updated": _day(order.status_updated_at.date()),
    }
    if order.confirmed_delivery_date:
        facts["confirmed_delivery_date"] = _day(order.confirmed_delivery_date)
    if window := _window(order.estimate_from, order.estimate_to):
        facts["estimated_delivery_window"] = f"{window} (estimate, not confirmed)"
    if previous := _window(order.previous_estimate_from, order.previous_estimate_to):
        facts["previous_estimate"] = previous
    facts["reason_for_change"] = order.status_reason or "none recorded"
    warnings: list[str] = []
    if now - order.status_updated_at > STALE_AFTER:
        warnings.append("the status hasn't been updated for weeks and may be outdated")
    if (
        order.status != "delivered"
        and order.estimate_to is not None
        and order.estimate_to < today
        and order.confirmed_delivery_date is None
    ):
        warnings.append("the estimated window has already passed without a new one")
    if (
        order.status != "delivered"
        and order.confirmed_delivery_date is None
        and order.estimate_from is None
    ):
        warnings.append("no delivery date or estimate is available")
    if warnings:
        facts["reliability_warning"] = (
            "; ".join(warnings)
            + ". Don't present any date as current; offer a colleague to clarify."
        )
    return facts


async def _shielded[T](write: Awaitable[T]) -> T:
    """Runs a write to its end, even when the turn is cancelled meanwhile."""
    done: list[T] = []
    with anyio.CancelScope(shield=True):
        done.append(await write)
    return done[0]


def _locked(kind: str) -> dict[str, Any]:
    return {
        "status": "locked",
        "instruction": (
            f"The {kind} identification failed {MAX_FAILED_LOOKUPS} times in this "
            "call. Don't try again; offer a colleague or general information."
        ),
    }


async def lookup_order(
    ctx: RunContext[CallDeps],
    order_number: str,
    customer_name: str,
    postal_code: str,
    vehicle_model: str,
) -> dict[str, Any]:
    """Identify the caller and get the delivery status of their order.

    All four details must come from the caller. Pass an empty string for a
    detail they haven't given yet; the result says which are missing.

    Args:
        order_number: The order number as the caller said it.
        customer_name: The name on the order, as the caller said it.
        postal_code: The postal code on the order.
        vehicle_model: The ordered model as the caller named it, e.g. "X5".
    """
    deps = ctx.deps
    state = deps.state
    if state.failed_order_lookups >= MAX_FAILED_LOOKUPS:
        await deps.record(ToolEvent("lookup_order", "refused", "Order check locked"))
        return _locked("order")
    given = {
        "order_number": digits(order_number),
        "customer_name": customer_name.strip(),
        "postal_code": digits(postal_code),
        "vehicle_model": vehicle_model.strip(),
    }
    missing = [field for field, value in given.items() if not value]
    if missing:
        return {
            "status": "incomplete",
            "missing": missing,
            "instruction": "Ask the caller for the next missing detail.",
        }
    order = await deps.crm.get_order(given["order_number"])
    customer = await deps.crm.get_customer(order.customer_id) if order else None
    if (
        order is None
        or customer is None
        or not name_matches(customer_name, customer.first_name, customer.last_name)
        or given["postal_code"] != customer.postal_code
        or not model_matches(vehicle_model, order.model)
    ):
        state.failed_order_lookups += 1
        left = MAX_FAILED_LOOKUPS - state.failed_order_lookups
        await deps.record(
            ToolEvent(
                "lookup_order",
                "refused",
                f"Order details didn't match ({state.failed_order_lookups} of "
                f"{MAX_FAILED_LOOKUPS})",
            )
        )
        return {
            "status": "no_match",
            "attempts_left": left,
            "instruction": (
                "The details don't match an order. Don't say which detail is "
                "wrong. "
                + (
                    "Say you couldn't match the details and ask the caller to repeat "
                    "the order number and the postal code digit by digit. Don't "
                    "offer a transfer yet unless the caller asks for one."
                    if left
                    else "Don't try again; offer a colleague or general information."
                )
            ),
        }
    now = deps.now()
    facts = _order_facts(order, now.date(), now)
    name = f"{customer.first_name} {customer.last_name}"
    state.verified_orders = [
        o for o in state.verified_orders if o.order_number != order.order_number
    ]
    state.verified_orders.append(
        VerifiedOrder(
            order_number=order.order_number,
            customer_name=name,
            facts="; ".join(f"{key}: {value}" for key, value in facts.items()),
        )
    )
    await deps.record(
        ToolEvent(
            "lookup_order",
            "ok",
            f"Order {order.order_number} verified",
            {"order_number": order.order_number},
        )
    )
    return {"status": "verified", "customer_name": name, "order": facts}


def _ticket_summary(ticket: TicketDetail) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "reference": ticket.reference,
        "topic": ticket.topic,
        "status": ticket.status.replace("_", " "),
        "priority": ticket.priority,
        "summary": ticket.summary,
        "opened": _day(ticket.created_at.date()),
        "last_update": _day(ticket.updated_at.date()),
    }
    if ticket.vehicle_model:
        summary["vehicle"] = ticket.vehicle_model
    if ticket.notes:
        summary["latest_note"] = ticket.notes[-1].body
    return summary


async def find_open_tickets(
    ctx: RunContext[CallDeps],
    last_name: str,
    ticket_reference: str = "",
    order_number: str = "",
    mobile_phone: str = "",
) -> dict[str, Any]:
    """Find the caller's open tickets, e.g. when they refer to an earlier call.

    Needs the caller's last name and one identifier: a ticket reference, an
    order number or a phone number. Without one, the phone line's number is
    used.

    Args:
        last_name: The caller's last name.
        ticket_reference: The ticket reference if the caller has it, e.g. "CC-10003".
        order_number: An order number the caller gave.
        mobile_phone: A phone number the caller gave, if not the one they call from.
    """
    deps = ctx.deps
    state = deps.state
    if state.failed_ticket_lookups >= MAX_FAILED_LOOKUPS:
        await deps.record(
            ToolEvent("find_open_tickets", "refused", "Ticket search locked")
        )
        return _locked("ticket")
    if not last_name.strip():
        return {"status": "incomplete", "missing": ["last_name"]}
    number = int(n) if (n := digits(ticket_reference)) else None
    order = digits(order_number) or None
    phone = normalize_phone(mobile_phone) if mobile_phone else None
    if number is None and order is None and phone is None:
        phone = state.caller_phone
    if number is None and order is None and phone is None:
        return {
            "status": "incomplete",
            "missing": ["ticket_reference, order_number or mobile_phone"],
        }
    candidates = await deps.crm.search_tickets(
        number=number, order_number=order, mobile_phone=phone
    )
    customers = {
        t.customer_id: await deps.crm.get_customer(t.customer_id)
        for t in candidates
        if t.customer_id is not None
    }
    matching = [
        t
        for t in candidates
        if t.customer_id is not None
        and (customer := customers.get(t.customer_id)) is not None
        and last_name_matches(last_name, customer.last_name)
    ]
    if not matching:
        state.failed_ticket_lookups += 1
        left = MAX_FAILED_LOOKUPS - state.failed_ticket_lookups
        await deps.record(
            ToolEvent(
                "find_open_tickets",
                "refused",
                f"No ticket for these details ({state.failed_ticket_lookups} of "
                f"{MAX_FAILED_LOOKUPS})",
            )
        )
        return {
            "status": "not_found",
            "attempts_left": left,
            "instruction": (
                "No ticket matches these details. Don't speculate why. "
                + (
                    "You may ask for another identifier (ticket, order or phone number)."
                    if left
                    else "Don't search again; offer a new ticket or a colleague."
                )
            ),
        }
    open_tickets = [t for t in matching if t.status in OPEN_STATUSES]
    for ticket in open_tickets:
        if state.ticket(ticket.reference) is None:
            state.tickets.append(
                CallTicket(
                    reference=ticket.reference,
                    topic=ticket.topic,
                    status=ticket.status,
                    origin="found",
                    summary=ticket.summary,
                )
            )
    references = ", ".join(t.reference for t in open_tickets)
    await deps.record(
        ToolEvent(
            "find_open_tickets",
            "ok",
            f"Open tickets: {references}" if open_tickets else "No open tickets",
            {"tickets": [t.reference for t in open_tickets]},
        )
    )
    return {
        "status": "found" if open_tickets else "none_open",
        "open_tickets": [_ticket_summary(t) for t in open_tickets],
        "closed_tickets": len(matching) - len(open_tickets),
    }


async def add_ticket_note(
    ctx: RunContext[CallDeps],
    ticket_reference: str,
    note: str,
    raise_priority_to: Priority | None = None,
) -> dict[str, Any]:
    """Add new information from the caller to one of their open tickets.

    Only for tickets found or created in this call.

    Args:
        ticket_reference: The ticket, e.g. "CC-10003".
        note: What's new, in one to three sentences, in the conversation
            language: what the caller reported, tried or wants now.
        raise_priority_to: Only if the situation became more urgent (e.g.
            the caller is now stranded).
    """
    deps = ctx.deps
    state = deps.state
    number = digits(ticket_reference)
    ticket = state.ticket(f"CC-{number}") if number else None
    if ticket is None:
        await deps.record(
            ToolEvent(
                "add_ticket_note", "refused", "Ticket not identified in this call"
            )
        )
        return {
            "status": "not_allowed",
            "instruction": (
                "You can only update a ticket found with find_open_tickets or "
                "created in this call."
            ),
        }
    updated = await _shielded(
        deps.crm.add_note(
            int(number),
            "carrie",
            redact_payment_data(note.strip()),
            deps.conversation_id,
            raise_priority_to,
        )
    )
    ticket.notes_added += 1
    ticket.status = updated.status
    await deps.record(
        ToolEvent(
            "add_ticket_note",
            "ok",
            f"Note added to {ticket.reference}",
            {"ticket": ticket.reference},
        )
    )
    return {
        "status": "added",
        "ticket": ticket.reference,
        "ticket_status": updated.status.replace("_", " "),
        "priority": updated.priority,
    }


async def create_ticket(
    ctx: RunContext[CallDeps],
    topic: Topic,
    issue_type: str,
    summary: str,
    order_number: str,
    priority: Priority = "normal",
    requested_outcome: str = "",
    details: dict[str, str] | None = None,
    mobile_phone: str = "",
) -> dict[str, Any]:
    """Open a ticket so the responsible team follows up on an unresolved concern.

    Needs an order number from the caller (unverified is fine, never invent
    one). The phone line's number is used unless the caller gives another.

    Args:
        topic: Which kind of concern.
        issue_type: A short label, e.g. delivery_delay, charging_interrupted,
            login_or_pairing_problem, warranty_claim_rejected,
            service_charge_dispute.
        summary: The concern in one or two sentences, in the conversation
            language, with the facts a colleague needs.
        order_number: The order number the caller gave.
        priority: high for a time-critical or repeated problem, urgent for a
            stranded caller, safety for a safety or security concern.
        requested_outcome: What the caller wants, in their words.
        details: Other facts the caller reported, e.g. vehicle_model,
            charging_location, error_message, attempted_steps, mileage_km,
            service_location_type, invoice_amount.
        mobile_phone: Only if the caller wants to be reached at another number.
    """
    deps = ctx.deps
    state = deps.state
    order = digits(order_number)
    phone = (
        normalize_phone(mobile_phone) if mobile_phone else None
    ) or state.caller_phone
    missing = [
        name
        for name, value in (("order_number", order), ("mobile_phone", phone))
        if not value
    ]
    if missing:
        await deps.record(
            ToolEvent("create_ticket", "refused", "Ticket needs " + ", ".join(missing))
        )
        return {
            "status": "missing",
            "missing": missing,
            "instruction": (
                "A ticket needs an order number and a phone number. Ask for "
                "what's missing; if the caller has no order number, offer a "
                "direct transfer instead. Never invent one."
            ),
        }
    if existing := next(
        (t for t in state.tickets if t.topic == topic and t.origin == "created"),
        None,
    ):
        return {
            "status": "exists",
            "ticket": existing.reference,
            "instruction": "A ticket for this topic exists; add a note to it instead.",
        }
    verified = any(o.order_number == order for o in state.verified_orders)
    facts = {k: redact_payment_data(v) for k, v in (details or {}).items() if v}
    if requested_outcome:
        facts["requested_outcome"] = redact_payment_data(requested_outcome)
    ticket = await _shielded(
        deps.crm.create_ticket(
            NewTicket(
                topic=topic,
                issue_type=issue_type,
                priority=priority,
                summary=redact_payment_data(summary.strip()),
                details=facts,
                order_number=order,
                mobile_phone=phone,
                verification_status="order_verified" if verified else "unverified",
                language=state.language,
                conversation_id=deps.conversation_id,
            )
        )
    )
    state.tickets.append(
        CallTicket(
            reference=ticket.reference,
            topic=topic,
            status=ticket.status,
            origin="created",
            summary=ticket.summary,
        )
    )
    await deps.record(
        ToolEvent(
            "create_ticket",
            "ok",
            f"Ticket {ticket.reference} created",
            {"ticket": ticket.reference},
        )
    )
    return {
        "status": "created",
        "ticket": ticket.reference,
        "spoken_reference": " ".join(ticket.reference.replace("-", "")),
        "callback_number": phone,
    }


async def handover_to_human(
    ctx: RunContext[CallDeps],
    route: Route,
    reason: str,
    summary: str,
    priority: Priority = "normal",
    requested_outcome: str = "",
    ticket_reference: str = "",
    other_issues: str = "",
) -> dict[str, Any]:
    """Transfer the call to a colleague, with a summary so the caller needn't repeat.

    Needs no customer data. Use it right away when the caller asks for a
    person, and when they accept your offer of a colleague.

    Args:
        route: The team: delivery, technical_support (charging, app),
            warranty_service, account_security, roadside_assistance (stranded,
            low battery), language_support (unsupported language), general.
        reason: Why a person is needed, in a few words.
        summary: Concise handover summary in the conversation language: the
            issue, the vehicle, what was tried, what the caller wants, what's
            verified and what's only reported.
        priority: high, urgent (stranded, time-critical) or safety when it applies.
        requested_outcome: What the caller wants, in their words.
        ticket_reference: A ticket of this call this is about, if any.
        other_issues: Other open concerns of the caller, briefly.
    """
    deps = ctx.deps
    state = deps.state
    ticket = (
        state.ticket(f"CC-{digits(ticket_reference)}") if ticket_reference else None
    )
    available = route not in deps.settings.unavailable_routes
    language = language_name(state.language)
    fields: dict[str, Any] = {
        "language": language,
        "caller_phone": state.caller_phone,
        "requested_outcome": requested_outcome or None,
        "verified_orders": [
            f"{o.order_number} ({o.customer_name})" for o in state.verified_orders
        ],
        "tickets": [t.reference for t in state.tickets],
        "other_issues": other_issues or None,
        "danger_reported": state.emergency,
    }
    await _shielded(
        deps.crm.create_handover(
            NewHandover(
                conversation_id=deps.conversation_id,
                ticket_number=int(ticket.reference[3:]) if ticket else None,
                route=route,
                priority=priority,
                language=state.language,
                reason=redact_payment_data(reason.strip()),
                summary=(
                    f"Language: {language}. " + redact_payment_data(summary.strip())
                ),
                details={k: v for k, v in fields.items() if v},
                status="transferred" if available else "unavailable",
            )
        )
    )
    team = route.replace("_", " ")
    state.handovers.append(
        CallHandover(route=route, status="transferred" if available else "unavailable")
    )
    if not available:
        await deps.record(
            ToolEvent(
                "handover_to_human",
                "failed",
                f"No colleague available in {team}",
                {"route": route},
            )
        )
        return {
            "status": "unavailable",
            "instruction": (
                f"No colleague in {team} is available right now. Say so plainly "
                "and apologize once. Offer only what you can do yourself, such as "
                "a ticket so the team follows up; don't promise a callback or time."
            ),
        }
    state.hold_requested = True
    await deps.record(
        ToolEvent(
            "handover_to_human",
            "ok",
            f"Transferred to {team} ({language})",
            {"route": route, "language": state.language},
        )
    )
    instruction = (
        f"Tell the caller in one short sentence that you're connecting them "
        f"with {team} now and they'll be on hold for a moment. Ask nothing else."
    )
    if route == "account_security":
        instruction += (
            " Before that, tell them not to share passwords or verification codes "
            "with anyone who asks, and that you haven't changed any settings."
        )
    return {"status": "transferred", "instruction": instruction}


async def set_language(ctx: RunContext[CallDeps], language: str) -> dict[str, Any]:
    """Switch the conversation language when the caller speaks or asks for another one.

    Args:
        language: ISO 639-1 code of the caller's language, e.g. "de", "en", "fr".
    """
    deps = ctx.deps
    state = deps.state
    code = language.strip().lower()[:2]
    supported = deps.settings.supported_languages
    names = " and ".join(language_name(c) for c in supported)
    if code not in supported:
        await deps.record(
            ToolEvent(
                "set_language",
                "refused",
                f"{language_name(code)} isn't supported",
                {"language": code},
            )
        )
        return {
            "status": "unsupported",
            "instruction": (
                f"Only {names} are supported. Keep the conversation language, "
                "explain this briefly, and offer a transfer with the route "
                "language_support."
            ),
        }
    changed = code != state.language
    state.language = code
    if changed:
        await deps.record(
            ToolEvent(
                "set_language",
                "ok",
                f"Language: {language_name(code)}",
                {"language": code},
            )
        )
    return {"status": "ok", "language": language_name(code)}


TOOLS = (
    lookup_order,
    find_open_tickets,
    add_ticket_note,
    create_ticket,
    handover_to_human,
    set_language,
)


def tool_names() -> tuple[str, ...]:
    return tuple(tool.__name__ for tool in TOOLS)
