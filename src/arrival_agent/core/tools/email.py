"""Tool: send a note to the hotel — MOCKED.

Real outbound email to a hotel means SMTP, deliverability, and messaging a real
business from a demo. So, like flight status and order placement, it's mocked:
the agent DRAFTS the note and the user taps Send. This returns a confirmation
the UI shows as a sent artifact.

The agent never sends on its own. The draft is prepared automatically (safe,
reversible), but the send is the user's tap — the pause point in the notify-hotel
to-do. Bounded authority: act where it's free, ask where it isn't.
"""

from __future__ import annotations

from uuid import uuid4

from arrival_agent.core.metrics import instrumented


@instrumented("send_hotel_note")
def send_hotel_note(hotel: str, note: str) -> dict:
    """Send the drafted late-arrival note to the hotel (mocked). Called only when
    the user taps Send. Returns a mock confirmation echoing the note."""
    return {
        "message_id": f"mock-{uuid4().hex[:8]}",
        "status": "sent",
        "to": hotel or "hotel front desk",
        "note": note,
    }
