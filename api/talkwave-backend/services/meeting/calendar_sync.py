"""Calendar sync service for auto-join meeting agent.

Connects to Google Calendar (and optionally Outlook) via Composio to:
  1. Fetch upcoming events with video meeting links
  2. Extract Zoom, Google Meet, and Teams URLs from events
  3. Feed them to the auto-join scheduler

Uses the existing ComposioService.execute_action() pattern to call
GOOGLECALENDAR_FIND_EVENT and OUTLOOK_GET_CALENDAR_VIEW.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from pydantic import BaseModel


MEETING_URL_PATTERNS = [
    re.compile(r"https?://[\w.-]*zoom\.us/j/\d+[^\s\"<>]*", re.IGNORECASE),
    re.compile(r"https?://meet\.google\.com/[\w-]+", re.IGNORECASE),
    re.compile(r"https?://teams\.microsoft\.com/l/meetup-join/[^\s\"<>]+", re.IGNORECASE),
    re.compile(r"https?://[\w.-]*webex\.com/[\w.-]+/j\.php\?[^\s\"<>]+", re.IGNORECASE),
]


class CalendarEvent(BaseModel):
    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    meeting_url: Optional[str] = None
    organizer: Optional[str] = None
    attendees: list[str] = []
    source: str = "google"
    raw: dict = {}


def extract_meeting_url(text: str) -> Optional[str]:
    """Extract the first meeting URL from text (event description, location, etc.)."""
    if not text:
        return None
    for pattern in MEETING_URL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _parse_google_event(event: dict, require_url: bool = True) -> Optional[CalendarEvent]:
    """Parse a single Google Calendar event dict into a CalendarEvent."""
    event_id = event.get("id", "")
    title = event.get("summary", "Untitled")

    start_raw = event.get("start", {})
    end_raw = event.get("end", {})
    start_str = start_raw.get("dateTime") or start_raw.get("date", "")
    end_str = end_raw.get("dateTime") or end_raw.get("date", "")

    if not start_str:
        return None

    try:
        start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else start_time + timedelta(hours=1)
    except ValueError:
        return None

    url = None
    if event.get("hangoutLink"):
        url = event["hangoutLink"]
    if not url:
        url = extract_meeting_url(event.get("location", ""))
    if not url:
        url = extract_meeting_url(event.get("description", ""))
    if not url:
        conf = event.get("conferenceData", {})
        for ep in conf.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                url = ep.get("uri")
                break

    if not url and require_url:
        return None

    organizer = event.get("organizer", {}).get("email", "")
    attendees = [a.get("email", "") for a in event.get("attendees", []) if a.get("email")]

    return CalendarEvent(
        event_id=event_id,
        title=title,
        start_time=start_time,
        end_time=end_time,
        meeting_url=url,
        organizer=organizer,
        attendees=attendees,
        source="google",
        raw=event,
    )


def _parse_outlook_event(event: dict, require_url: bool = True) -> Optional[CalendarEvent]:
    """Parse a single Outlook calendar event dict into a CalendarEvent."""
    event_id = event.get("id", "")
    title = event.get("subject", "Untitled")

    start_raw = event.get("start", {})
    end_raw = event.get("end", {})
    start_str = start_raw.get("dateTime", "")
    end_str = end_raw.get("dateTime", "")

    if not start_str:
        return None

    try:
        start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else start_time + timedelta(hours=1)
    except ValueError:
        return None

    url = None
    online = event.get("onlineMeeting", {})
    if online and online.get("joinUrl"):
        url = online["joinUrl"]
    if not url:
        url = extract_meeting_url(event.get("location", {}).get("displayName", ""))
    if not url:
        url = extract_meeting_url(event.get("bodyPreview", ""))
    if not url:
        body = event.get("body", {}).get("content", "")
        url = extract_meeting_url(body)

    if not url and require_url:
        return None

    organizer = event.get("organizer", {}).get("emailAddress", {}).get("address", "")
    attendees = [
        a.get("emailAddress", {}).get("address", "")
        for a in event.get("attendees", [])
        if a.get("emailAddress", {}).get("address")
    ]

    return CalendarEvent(
        event_id=event_id,
        title=title,
        start_time=start_time,
        end_time=end_time,
        meeting_url=url,
        organizer=organizer,
        attendees=attendees,
        source="outlook",
        raw=event,
    )


def _extract_events_from_composio_response(data: dict, list_keys: list[str]) -> list[dict]:
    """Walk the Composio response structure to find the events array.

    Composio wraps Google Calendar results as:
      { "data": { ..., "event_data": { "event_data": [...] } }, "successful": true }
    """
    if not isinstance(data, dict):
        return list(data) if isinstance(data, list) else []

    for k in list_keys:
        val = data.get(k)
        if isinstance(val, list) and val:
            return val

    inner = data.get("data")
    if isinstance(inner, dict):
        for k in list_keys:
            val = inner.get(k)
            if isinstance(val, list) and val:
                return val
        ed = inner.get("event_data")
        if isinstance(ed, dict):
            inner_list = ed.get("event_data")
            if isinstance(inner_list, list):
                return inner_list
    elif isinstance(inner, list) and inner:
        return inner

    ed = data.get("event_data")
    if isinstance(ed, dict):
        inner_list = ed.get("event_data")
        if isinstance(inner_list, list):
            return inner_list

    return []


class CalendarSyncService:
    """Fetches upcoming meetings from connected calendars via Composio."""

    async def fetch_upcoming_meetings(
        self,
        organization_id: int,
        lookahead_minutes: int = 30,
        provider: str = "google",
        require_meeting_url: bool = True,
    ) -> list[CalendarEvent]:
        """Fetch upcoming calendar events.

        Args:
            organization_id: Org ID for Composio entity lookup.
            lookahead_minutes: How far ahead to look for meetings.
            provider: "google" or "outlook".
            require_meeting_url: If False, include events without video links.
        """
        from api.services.integrations.composio_service import composio_service

        now = datetime.now(timezone.utc)
        time_min = now - timedelta(hours=2)
        time_max = now + timedelta(minutes=lookahead_minutes)

        events: list[CalendarEvent] = []

        if provider == "google":
            events = await self._fetch_google_events(
                composio_service, organization_id, time_min, time_max, require_meeting_url
            )
        elif provider == "outlook":
            events = await self._fetch_outlook_events(
                composio_service, organization_id, time_min, time_max, require_meeting_url
            )

        logger.info(
            f"[CalendarSync] Found {len(events)} upcoming meetings "
            f"(org={organization_id}, provider={provider}, "
            f"window={lookahead_minutes}min)"
        )
        return events

    async def _fetch_google_events(
        self, composio_svc, org_id, time_min, time_max, require_url=True
    ):
        try:
            result = await composio_svc.execute_action(
                organization_id=org_id,
                app_id="googlecalendar",
                action_name="GOOGLECALENDAR_FIND_EVENT",
                params={
                    "time_min": time_min.replace(microsecond=0).isoformat(),
                    "time_max": time_max.replace(microsecond=0).isoformat(),
                    "max_results": 50,
                    "single_events": True,
                    "order_by": "startTime",
                    "calendar_id": "primary",
                },
            )

            if not result.success:
                logger.warning(f"[CalendarSync] Google Calendar fetch failed: {result.error}")
                return []

            data = result.data or {}
            raw_events = _extract_events_from_composio_response(
                data, ["items", "events"]
            )

            logger.debug(
                f"[CalendarSync] Google raw events count: {len(raw_events)} "
                f"(response keys: {list(data.keys()) if isinstance(data, dict) else 'non-dict'})"
            )

            events = []
            for raw in raw_events:
                parsed = _parse_google_event(raw, require_url=require_url)
                if parsed:
                    events.append(parsed)

            return events

        except Exception as e:
            logger.error(f"[CalendarSync] Google Calendar error: {e}", exc_info=True)
            return []

    async def _fetch_outlook_events(
        self, composio_svc, org_id, time_min, time_max, require_url=True
    ):
        try:
            result = await composio_svc.execute_action(
                organization_id=org_id,
                app_id="outlookcalendar",
                action_name="OUTLOOK_GET_CALENDAR_VIEW",
                params={
                    "start_datetime": time_min.replace(microsecond=0).isoformat(),
                    "end_datetime": time_max.replace(microsecond=0).isoformat(),
                    "top": 50,
                },
            )

            if not result.success:
                logger.warning(f"[CalendarSync] Outlook fetch failed: {result.error}")
                return []

            data = result.data or {}
            raw_events = _extract_events_from_composio_response(
                data, ["value", "events"]
            )

            events = []
            for raw in raw_events:
                parsed = _parse_outlook_event(raw, require_url=require_url)
                if parsed:
                    events.append(parsed)

            return events

        except Exception as e:
            logger.error(f"[CalendarSync] Outlook Calendar error: {e}", exc_info=True)
            return []


calendar_sync_service = CalendarSyncService()
