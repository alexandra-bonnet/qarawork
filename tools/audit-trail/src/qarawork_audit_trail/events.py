"""Validate event-list consistency, never claim independently trusted provenance."""
from __future__ import annotations

from datetime import datetime, timezone
import re

DIGEST = re.compile(r"[0-9a-fA-F]{64}\Z")
MAX_EVENTS = 1000


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Event timestamp must be an ISO-8601 string.")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Event timestamp is invalid.") from exc
    if dt.tzinfo is None:
        raise ValueError("Event timestamp must include a timezone.")
    return dt.astimezone(timezone.utc)


def review_event_sequence(events: list[dict], *, expected_object_id: str) -> dict:
    """Assess supplied chronological observations without fabricating missing events.

    An internally consistent submitted list is NOT proof that all actual edits
    occurred in it, or that events, actor IDs, signatures or timestamps are real.
    """
    if not isinstance(expected_object_id, str) or not expected_object_id.strip():
        raise ValueError("expected_object_id is required.")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("Event list must contain at most 1000 entries.")
    findings: list[dict] = []
    cleaned = []
    seen: set[str] = set()
    previous_time = None
    previous_seq = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            findings.append({"index": index, "code": "MALFORMED_EVENT", "detail": "Event is not an object."})
            continue
        identifier = event.get("event_id")
        seq = event.get("sequence")
        actor = event.get("actor_id")
        event_time = event.get("timestamp")
        object_id = event.get("object_id")
        operation = event.get("operation")
        digest = event.get("content_sha256")
        if not isinstance(identifier, str) or not identifier.strip():
            findings.append({"index": index, "code": "MISSING_EVENT_ID"})
        elif identifier in seen:
            findings.append({"index": index, "code": "DUPLICATE_EVENT_ID"})
        else:
            seen.add(identifier)
        if object_id != expected_object_id:
            findings.append({"index": index, "code": "OBJECT_MISMATCH"})
        if not isinstance(actor, str) or not actor.strip():
            findings.append({"index": index, "code": "ACTOR_MISSING"})
        if not isinstance(operation, str) or not operation.strip():
            findings.append({"index": index, "code": "OPERATION_MISSING"})
        if not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0:
            findings.append({"index": index, "code": "INVALID_SEQUENCE"})
        elif previous_seq is not None:
            if seq != previous_seq + 1:
                findings.append({"index": index, "code": "SEQUENCE_GAP_OR_REORDER",
                                 "detail": f"Expected {previous_seq + 1}, got {seq}."})
        if isinstance(seq, int) and not isinstance(seq, bool) and seq > 0:
            previous_seq = seq
        try:
            instant = _instant(event_time)
        except ValueError:
            findings.append({"index": index, "code": "INVALID_TIMESTAMP"})
        else:
            if previous_time is not None and instant < previous_time:
                findings.append({"index": index, "code": "TIME_REVERSED"})
            previous_time = instant
        if digest is not None and (not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
            findings.append({"index": index, "code": "INVALID_DIGEST"})
        cleaned.append({
            "event_id": identifier,
            "sequence": seq, "timestamp": event_time,
            "object_id": object_id, "operation": operation,
            "actor_id": actor, "content_sha256": digest,
        })
    if not events:
        findings.append({"index": None, "code": "NO_EVENTS_SUPPLIED"})
    return {
        "object_id": expected_object_id,
        "supplied_event_count": len(events),
        "events": cleaned,
        "findings": findings,
        "internal_consistency_passed": not findings,
        "audit_trail_complete": False,
        "actor_identity_verified": False,
        "event_provenance_independently_verified": False,
        "authorized_for_use": False,
        "next_action": (
            "Investigate reported event-list gaps and obtain independently preserved source records."
            if findings else
            "Corroborate this internally consistent event list against independently preserved source records."
        ),
        "notice": (
            "These are caller-supplied observations, NOT a provider audit-log export. "
            "Even a consistent list cannot prove omitted events are absent, actor "
            "identities are authentic, or event records are immutable."
        ),
    }
