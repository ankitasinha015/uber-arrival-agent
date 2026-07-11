"""Domain: turn a booking-confirmation email into an itinerary.

The agent's entry point in the real product is your inbox: a booking email
arrives, and the agent extracts the trip (flight, arrival airport, hotel,
scheduled arrival) without you typing anything. This is a genuine capability
worth showing — structured extraction from messy human text.

    extract_itinerary(email_text) -> {flight_no, airport, hotel, scheduled_arrival}

In production this is an LLM call (see `_extract_via_llm`, same tool-use pattern
as choice_set). For the demo it falls back to a deterministic parse of the
booking-email format below — honest, offline, and cache-free, exactly like the
flight and order tools are mocked. `use_llm=False` forces the parse (tests).

The extracted dict matches the `scenario.itinerary` shape the adapters already
consume, so an email-sourced trip is a drop-in for a scenario-sourced one.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_PACIFIC = timezone(timedelta(hours=-7))  # demo airports are Pacific; mocked


def sample_booking_email() -> str:
    """A realistic booking-confirmation email the demo ingests."""
    return (
        "From: Uber Travel <travel@uber.com>\n"
        "Subject: Your trip is booked — UA 517 to San Francisco\n\n"
        "Hi Ankit,\n\n"
        "Your flight is confirmed:\n"
        "  United Airlines UA 517\n"
        "  Newark (EWR) -> San Francisco (SFO)\n"
        "  Wed, May 20 - departs 8:05 PM - arrives 11:15 PM\n\n"
        "Your hotel:\n"
        "  Hotel Zephyr, San Francisco\n"
        "  Check-in: Wed, May 20\n\n"
        "Safe travels.\n"
    )


def _parse_arrival(text: str, *, year: int = 2026) -> datetime | None:
    """Pull the arrival date + time out of the booking email."""
    m_date = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\b", text)
    m_time = re.search(r"arrives\s+(\d{1,2}):(\d{2})\s*([AP]M)", text, re.I)
    if not (m_date and m_time):
        return None
    month = _MONTHS.get(m_date.group(1).lower())
    if month is None:
        return None
    day = int(m_date.group(2))
    hour, minute, ampm = int(m_time.group(1)), int(m_time.group(2)), m_time.group(3).upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return datetime(year, month, day, hour, minute, tzinfo=_PACIFIC)


def _extract_via_parse(email_text: str) -> dict:
    """Deterministic parse of the booking-email format. The demo path."""
    flight = re.search(r"\b([A-Z]{2})\s?(\d{2,4})\b", email_text)
    arr_airport = re.search(r"->\s*[^(]+\(([A-Z]{3})\)", email_text)
    hotel = re.search(r"hotel:\s*\n\s*(.+)", email_text, re.I)
    arrival = _parse_arrival(email_text)
    return {
        "flight_no": f"{flight.group(1)} {flight.group(2)}" if flight else None,
        "airport": arr_airport.group(1) if arr_airport else None,
        "hotel": hotel.group(1).strip() if hotel else None,
        "scheduled_arrival": arrival.isoformat() if arrival else None,
    }


def _extract_via_llm(email_text: str, *, client=None) -> dict:
    """Production path: an LLM tool-use call returns the structured itinerary.
    Kept thin; raises on any error so `extract_itinerary` falls back to the parse."""
    from arrival_agent.core.config import anthropic_key

    import anthropic

    client = client or anthropic.Anthropic(api_key=anthropic_key())
    tool = {
        "name": "record_itinerary",
        "description": "The trip extracted from the booking email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flight_no": {"type": "string"},
                "airport": {"type": "string", "description": "arrival airport IATA code"},
                "hotel": {"type": "string"},
                "scheduled_arrival": {"type": "string", "description": "ISO 8601 with timezone"},
            },
            "required": ["flight_no", "airport", "hotel", "scheduled_arrival"],
        },
    }
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_itinerary"},
        messages=[{
            "role": "user",
            "content": f"Extract the itinerary from this booking email:\n\n{email_text}",
        }],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError("no tool_use block in extraction response")


def extract_itinerary(email_text: str, *, use_llm: bool = True) -> dict:
    """Extract the itinerary from a booking email. Tries the LLM, falls back to a
    deterministic parse (offline/demo). `use_llm=False` forces the parse."""
    if use_llm:
        try:
            return _extract_via_llm(email_text)
        except Exception:
            pass  # fall through — the parse is the honest demo path
    return _extract_via_parse(email_text)
