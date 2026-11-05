"""The customer care system's starting data: 5 cases for each of the 4 topics.

Dates are offsets from the day of seeding, so delivery estimates, missed
dates and stale statuses mean the same whenever the data is loaded. Names,
phone numbers, VINs and order numbers are fictional.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from voice_agent.crm.records import NoteAuthor, Priority, TicketStatus, Topic

BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class SeedCustomer:
    first_name: str
    last_name: str
    postal_code: str
    city: str
    mobile_phone: str
    preferred_language: str = "de"

    @property
    def email(self) -> str:
        local = f"{self.first_name}.{self.last_name}".casefold()
        for umlaut, plain in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
            local = local.replace(umlaut, plain)
        return f"{local}@example.de"


@dataclass(frozen=True)
class SeedVehicle:
    vin: str
    model: str
    model_year: int
    powertrain: str
    # Days before the seed day
    registered_days_ago: int | None
    mileage_km: int | None


@dataclass(frozen=True)
class SeedOrder:
    order_number: str
    model: str
    status: str
    ordered_days_ago: int
    dealer: str
    status_updated_days_ago: int
    confirmed_in_days: int | None = None
    estimate_in_days: tuple[int, int] | None = None
    previous_estimate_in_days: tuple[int, int] | None = None
    status_reason: str | None = None


@dataclass(frozen=True)
class SeedNote:
    days_ago: int
    body: str
    author: NoteAuthor = "care_agent"


@dataclass(frozen=True)
class SeedTicket:
    topic: Topic
    issue_type: str
    status: TicketStatus
    priority: Priority
    summary: str
    created_days_ago: int
    details: dict[str, Any] = field(default_factory=dict[str, Any])
    notes: tuple[SeedNote, ...] = ()


@dataclass(frozen=True)
class SeedCase:
    key: str
    customer: SeedCustomer
    ticket: SeedTicket
    vehicle: SeedVehicle | None = None
    order: SeedOrder | None = None


def day(today: date, offset: int) -> date:
    return today + timedelta(days=offset)


def moment(today: date, days_ago: int, hour: int = 10) -> datetime:
    return datetime.combine(today - timedelta(days=days_ago), time(hour), BERLIN)


CASES: tuple[SeedCase, ...] = (
    # --- Delivery -------------------------------------------------------------
    SeedCase(
        "D1",
        SeedCustomer("Jana", "Müller", "10115", "Berlin", "+4915122000101"),
        order=SeedOrder(
            "456789",
            "BMW iX3 50 xDrive",
            "at_dealer",
            ordered_days_ago=160,
            dealer="BMW Autohaus Spree Berlin",
            status_updated_days_ago=1,
            confirmed_in_days=5,
        ),
        ticket=SeedTicket(
            "delivery",
            "delivery_status",
            "resolved",
            "normal",
            "Asked which documents are needed for the registration.",
            created_days_ago=12,
            details={"requested_outcome": "List of registration documents"},
            notes=(SeedNote(11, "Sent the document checklist by e-mail."),),
        ),
    ),
    SeedCase(
        "D2",
        SeedCustomer("Thomas", "Schneider", "80331", "München", "+4915122000102"),
        order=SeedOrder(
            "381204",
            "BMW i5 Touring eDrive40",
            "in_production",
            ordered_days_ago=95,
            dealer="BMW Niederlassung München",
            status_updated_days_ago=2,
            estimate_in_days=(14, 21),
        ),
        ticket=SeedTicket(
            "delivery",
            "delivery_status",
            "resolved",
            "normal",
            "Asked for a confirmed delivery date; only an estimate exists.",
            created_days_ago=20,
            notes=(
                SeedNote(
                    20,
                    "Explained that a confirmed appointment follows once the "
                    "vehicle has left production.",
                ),
            ),
        ),
    ),
    SeedCase(
        "D3",
        SeedCustomer("Katrin", "Weber", "50667", "Köln", "+4915122000103"),
        order=SeedOrder(
            "527713",
            "BMW X5 xDrive50e",
            "in_transit",
            ordered_days_ago=180,
            dealer="BMW Autohaus Rheinufer Köln",
            status_updated_days_ago=1,
            estimate_in_days=(7, 11),
            previous_estimate_in_days=(-10, -6),
        ),
        ticket=SeedTicket(
            "delivery",
            "delivery_delay",
            "open",
            "high",
            "Delivery missed the earlier estimate; the customer's lease ends "
            "tomorrow and she needs a replacement car.",
            created_days_ago=5,
            details={
                "requested_outcome": "Replacement car until delivery, cost coverage",
                "previous_contacts": 2,
            },
            notes=(
                SeedNote(5, "Customer called about the missed delivery window."),
                SeedNote(
                    3,
                    "Customer called again; asked dealer about a loan car, no answer yet.",
                ),
            ),
        ),
    ),
    SeedCase(
        "D4",
        SeedCustomer("Lukas", "Fischer", "70173", "Stuttgart", "+4915122000104"),
        order=SeedOrder(
            "610938",
            "BMW 330e Touring",
            "in_production",
            ordered_days_ago=210,
            dealer="BMW Autohaus Neckar Stuttgart",
            status_updated_days_ago=35,
            estimate_in_days=(-20, -14),
        ),
        ticket=SeedTicket(
            "delivery",
            "delivery_status",
            "open",
            "normal",
            "Status has not changed for weeks; the estimate has passed.",
            created_days_ago=9,
            notes=(SeedNote(8, "Asked logistics for a current status."),),
        ),
    ),
    SeedCase(
        "D5",
        SeedCustomer("Sabine", "Becker", "20095", "Hamburg", "+4915122000105"),
        order=SeedOrder(
            "702416",
            "BMW iX1 xDrive30",
            "in_production",
            ordered_days_ago=120,
            dealer="BMW Autohaus Alster Hamburg",
            status_updated_days_ago=3,
            estimate_in_days=(10, 15),
        ),
        ticket=SeedTicket(
            "delivery",
            "delivery_dealer_conflict",
            "waiting_on_customer",
            "normal",
            "Customer reports the dealer promised delivery in two days; the "
            "system shows a later estimate.",
            created_days_ago=4,
            details={"dealer_promise": "in two days (customer-reported)"},
            notes=(
                SeedNote(
                    4,
                    "Asked the customer for the dealer's written confirmation.",
                ),
            ),
        ),
    ),
    # --- Charging -------------------------------------------------------------
    SeedCase(
        "C1",
        SeedCustomer(
            "Markus", "Hoffmann", "60311", "Frankfurt am Main", "+4915122000201"
        ),
        vehicle=SeedVehicle(
            "WBA21CF0X0RC10201", "BMW iX xDrive45", 2025, "bev", 400, 18_500
        ),
        order=SeedOrder(
            "318842",
            "BMW iX xDrive45",
            "delivered",
            ordered_days_ago=560,
            dealer="BMW Autohaus Main Frankfurt",
            status_updated_days_ago=400,
        ),
        ticket=SeedTicket(
            "charging",
            "charging_interrupted",
            "open",
            "normal",
            "Home wallbox charging stops after a few minutes, repeatedly; no "
            "damage or heat reported.",
            created_days_ago=6,
            details={
                "charging_location": "home",
                "charging_type": "AC",
                "attempted_steps": "Reconnected the cable, restarted the session",
                "result": "unresolved",
            },
            notes=(SeedNote(4, "Electrician visit for the wallbox suggested."),),
        ),
    ),
    SeedCase(
        "C2",
        SeedCustomer("Anna", "Schulz", "04109", "Leipzig", "+4915122000202"),
        vehicle=SeedVehicle(
            "WBA71GV0X0FC10202", "BMW i4 eDrive40", 2024, "bev", 700, 31_000
        ),
        order=SeedOrder(
            "244517",
            "BMW i4 eDrive40",
            "delivered",
            ordered_days_ago=820,
            dealer="BMW Autohaus Leipzig Nord",
            status_updated_days_ago=700,
        ),
        ticket=SeedTicket(
            "charging",
            "authorization_failed",
            "resolved",
            "normal",
            "Public charger rejected the charging card; worked after retrying "
            "via the operator's app.",
            created_days_ago=30,
            details={"charging_location": "public", "result": "resolved"},
        ),
    ),
    SeedCase(
        "C3",
        SeedCustomer("Stefan", "Wagner", "90402", "Nürnberg", "+4915122000203"),
        vehicle=SeedVehicle(
            "WBA61FJ0X0CC10203", "BMW i5 eDrive40", 2025, "bev", 300, 12_400
        ),
        order=SeedOrder(
            "297361",
            "BMW i5 eDrive40",
            "delivered",
            ordered_days_ago=450,
            dealer="BMW Autohaus Franken Nürnberg",
            status_updated_days_ago=300,
        ),
        ticket=SeedTicket(
            "charging",
            "charging_limit",
            "closed",
            "normal",
            "Charging stopped at 80 percent; target charge level was set to 80.",
            created_days_ago=45,
            details={"charging_location": "home", "result": "resolved"},
        ),
    ),
    SeedCase(
        "C4",
        SeedCustomer("Julia", "Koch", "28195", "Bremen", "+4915122000204"),
        vehicle=SeedVehicle(
            "WBA11EE0X0DC10204", "BMW iX1 eDrive20", 2024, "bev", 500, 22_800
        ),
        order=SeedOrder(
            "263088",
            "BMW iX1 eDrive20",
            "delivered",
            ordered_days_ago=610,
            dealer="BMW Autohaus Weser Bremen",
            status_updated_days_ago=500,
        ),
        ticket=SeedTicket(
            "charging",
            "connector_stuck",
            "open",
            "normal",
            "Charging connector stayed locked after DC fast charging; released "
            "by the operator's hotline.",
            created_days_ago=3,
            details={
                "charging_location": "public",
                "charging_type": "DC",
                "result": "unresolved",
                "requested_action": "Check the charging port lock",
            },
        ),
    ),
    SeedCase(
        "C5",
        SeedCustomer("Michael", "Richter", "01067", "Dresden", "+4915122000205"),
        vehicle=SeedVehicle(
            "WBA71EJ0X0EC10205", "BMW i7 xDrive60", 2024, "bev", 650, 41_200
        ),
        order=SeedOrder(
            "251944",
            "BMW i7 xDrive60",
            "delivered",
            ordered_days_ago=760,
            dealer="BMW Autohaus Elbe Dresden",
            status_updated_days_ago=650,
        ),
        ticket=SeedTicket(
            "charging",
            "stranded_low_battery",
            "in_progress",
            "urgent",
            "Stranded with 4 percent battery, the only charger was out of "
            "order; roadside assistance arranged.",
            created_days_ago=8,
            details={"state_of_charge": "4 %", "urgency": "stranded"},
            notes=(SeedNote(8, "Roadside assistance towed the car to a charger."),),
        ),
    ),
    # --- Connected services / app ---------------------------------------------
    SeedCase(
        "A1",
        SeedCustomer("Laura", "Klein", "40213", "Düsseldorf", "+4915122000301"),
        vehicle=SeedVehicle(
            "WBA31DX0X0GC10301", "BMW X3 20d", 2024, "ice", 450, 27_300
        ),
        order=SeedOrder(
            "276120",
            "BMW X3 20d",
            "delivered",
            ordered_days_ago=560,
            dealer="BMW Autohaus Rhein Düsseldorf",
            status_updated_days_ago=450,
        ),
        ticket=SeedTicket(
            "connected_services",
            "stale_vehicle_data",
            "resolved",
            "normal",
            "Vehicle app showed an outdated fuel level; updated after reopening the app.",
            created_days_ago=25,
            details={"affected_feature": "vehicle status", "result": "resolved"},
        ),
    ),
    SeedCase(
        "A2",
        SeedCustomer("Andreas", "Wolf", "30159", "Hannover", "+4915122000302"),
        vehicle=SeedVehicle("WBA71GV0X0HC10302", "BMW i4 M50", 2025, "bev", 200, 9_800),
        order=SeedOrder(
            "339475",
            "BMW i4 M50",
            "delivered",
            ordered_days_ago=330,
            dealer="BMW Autohaus Leine Hannover",
            status_updated_days_ago=200,
        ),
        ticket=SeedTicket(
            "connected_services",
            "login_or_pairing_problem",
            "open",
            "normal",
            "Sign-in to the vehicle app fails with 'Something went wrong'.",
            created_days_ago=2,
            details={
                "phone_os": "iOS",
                "symptom_or_error": "Something went wrong",
                "attempted_steps": "Restarted the app, updated it",
            },
        ),
    ),
    SeedCase(
        "A3",
        SeedCustomer("Christina", "Schröder", "45127", "Essen", "+4915122000303"),
        vehicle=SeedVehicle(
            "WBA51FH0X0JC10303", "BMW 520d Touring", 2022, "ice", 1300, 68_000
        ),
        ticket=SeedTicket(
            "connected_services",
            "login_or_pairing_problem",
            "open",
            "normal",
            "Bought the car used; can't pair the vehicle app because the "
            "previous owner is still linked.",
            created_days_ago=7,
            details={"ownership": "used vehicle", "affected_feature": "pairing"},
            notes=(SeedNote(6, "Ownership documents requested by e-mail."),),
        ),
    ),
    SeedCase(
        "A4",
        SeedCustomer("Tobias", "Neumann", "55116", "Mainz", "+4915122000304"),
        vehicle=SeedVehicle(
            "WBA11HE0X0KC10304", "BMW iX2 eDrive20", 2025, "bev", 150, 7_100
        ),
        order=SeedOrder(
            "352806",
            "BMW iX2 eDrive20",
            "delivered",
            ordered_days_ago=280,
            dealer="BMW Autohaus Mainz",
            status_updated_days_ago=150,
        ),
        ticket=SeedTicket(
            "connected_services",
            "feature_unavailable",
            "open",
            "normal",
            "Remote climate control in the vehicle app shows 'not available'.",
            created_days_ago=4,
            details={"affected_feature": "remote climate", "phone_os": "Android"},
        ),
    ),
    SeedCase(
        "A5",
        SeedCustomer("Petra", "Schwarz", "24103", "Kiel", "+4915122000305"),
        vehicle=SeedVehicle(
            "WBA11EF0X0LC10305", "BMW X1 xDrive23i", 2024, "ice", 380, 19_900
        ),
        order=SeedOrder(
            "287213",
            "BMW X1 xDrive23i",
            "delivered",
            ordered_days_ago=500,
            dealer="BMW Autohaus Förde Kiel",
            status_updated_days_ago=380,
        ),
        ticket=SeedTicket(
            "connected_services",
            "security_or_access_concern",
            "in_progress",
            "safety",
            "Unknown phone listed as a connected device in the vehicle app.",
            created_days_ago=1,
            details={"urgency": "security"},
            notes=(SeedNote(1, "Security team reviewing the account's devices."),),
        ),
    ),
    # --- Warranty / service ---------------------------------------------------
    SeedCase(
        "W1",
        SeedCustomer("Daniel", "Zimmermann", "65183", "Wiesbaden", "+4915122000401"),
        vehicle=SeedVehicle(
            "WBA51DR0X0MC10401", "BMW 320d Limousine", 2023, "ice", 1100, 48_000
        ),
        order=SeedOrder(
            "198330",
            "BMW 320d Limousine",
            "delivered",
            ordered_days_ago=1200,
            dealer="BMW Autohaus Wiesbaden",
            status_updated_days_ago=1100,
        ),
        ticket=SeedTicket(
            "warranty",
            "warranty_claim_rejected",
            "open",
            "normal",
            "Air conditioning repair not covered according to the workshop; "
            "customer disagrees. Last service at an independent workshop.",
            created_days_ago=6,
            details={
                "repair_or_component": "air conditioning",
                "mileage_km": 48_000,
                "service_location_type": "independent",
            },
        ),
    ),
    SeedCase(
        "W2",
        SeedCustomer("Melanie", "Braun", "68159", "Mannheim", "+4915122000402"),
        vehicle=SeedVehicle(
            "WBA31DX0X0NC10402", "BMW X3 30e", 2024, "phev", 600, 26_500
        ),
        order=SeedOrder(
            "236871",
            "BMW X3 30e",
            "delivered",
            ordered_days_ago=720,
            dealer="BMW Autohaus Quadrate Mannheim",
            status_updated_days_ago=600,
        ),
        ticket=SeedTicket(
            "warranty",
            "service_charge_dispute",
            "open",
            "normal",
            "Disputes an invoice of 1,240 euros after the warranty request was declined.",
            created_days_ago=9,
            details={
                "invoice_amount": "1240 EUR",
                "requested_outcome": "Review of the charge",
            },
            notes=(SeedNote(7, "Invoice copy requested from the dealer."),),
        ),
    ),
    SeedCase(
        "W3",
        SeedCustomer("Frank", "Krüger", "33602", "Bielefeld", "+4915122000403"),
        vehicle=SeedVehicle("WBA11AA0X0PC10403", "BMW 118i", 2024, "ice", 730, 21_000),
        order=SeedOrder(
            "241156",
            "BMW 118i",
            "delivered",
            ordered_days_ago=800,
            dealer="BMW Autohaus Teutoburg Bielefeld",
            status_updated_days_ago=730,
        ),
        ticket=SeedTicket(
            "warranty",
            "warranty_general_question",
            "closed",
            "normal",
            "Asked which documents are useful for a warranty review.",
            created_days_ago=40,
        ),
    ),
    SeedCase(
        "W4",
        SeedCustomer("Nicole", "Hofmann", "79098", "Freiburg", "+4915122000404"),
        vehicle=SeedVehicle(
            "WBA21GF0X0QC10404", "BMW iX3 M Sport", 2024, "bev", 520, 33_700
        ),
        order=SeedOrder(
            "259903",
            "BMW iX3 M Sport",
            "delivered",
            ordered_days_ago=640,
            dealer="BMW Autohaus Breisgau Freiburg",
            status_updated_days_ago=520,
        ),
        ticket=SeedTicket(
            "warranty",
            "repeated_failed_repair",
            "open",
            "high",
            "Infotainment display fails again after three repairs.",
            created_days_ago=14,
            details={"repair_or_component": "infotainment display", "repairs": 3},
            notes=(
                SeedNote(12, "Third repair appointment completed."),
                SeedNote(2, "Customer reports the fault is back.", author="system"),
            ),
        ),
    ),
    SeedCase(
        "W5",
        SeedCustomer("Jörg", "Hartmann", "49074", "Osnabrück", "+4915122000405"),
        vehicle=SeedVehicle(
            "WBA51FL0X0RC10405", "BMW 530e Limousine", 2021, "phev", 1650, 92_000
        ),
        order=SeedOrder(
            "143207",
            "BMW 530e Limousine",
            "delivered",
            ordered_days_ago=1750,
            dealer="BMW Autohaus Osnabrück",
            status_updated_days_ago=1650,
        ),
        ticket=SeedTicket(
            "warranty",
            "goodwill_request",
            "closed",
            "normal",
            "Asked for goodwill on a high-voltage battery check after the "
            "warranty period; reviewed by the warranty team.",
            created_days_ago=60,
        ),
    ),
)
