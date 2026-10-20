"""Append only facts observed by the API and authenticated device sync."""

from .models import SessionEvent


def record(db, session, kind, source, key, data=None):
    # Callers hold the connector lock, so retries and concurrent device syncs
    # serialize before the uniqueness constraint is reached.
    db.add(SessionEvent(session_id=session.id, event_key=key, kind=kind, source=source, data=data))
