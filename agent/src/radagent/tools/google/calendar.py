"""
Google Calendar: reading the user's schedule and changing it

Times the model passes without an offset ("2026-10-03T09:00") are in the user's own time zone, the primary
calendar's, and results are shown in it too, so the model never has to work out offsets
"""
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from radagent.tools.google.client import CALENDAR_URL, call


EVENT_LIMIT: int = 250
# Calendars read at once for calendar="all"
MAX_CALENDARS: int = 25
DESCRIPTION_CHARS: int = 500
DEFAULT_DAYS: int = 7

_zone: ZoneInfo | None = None



def _calendar_path(calendar: str) -> str:
    return f"{CALENDAR_URL}/calendars/{quote(calendar or 'primary', safe = '')}"


def zone() -> ZoneInfo:
    """The user's time zone, from their primary calendar"""
    global _zone
    if _zone is None:
        name = (call("GET", _calendar_path("primary"), {"fields": "timeZone"}) or {}).get("timeZone") or "UTC"
        try:
            _zone = ZoneInfo(name)
        except ZoneInfoNotFoundError:
            _zone = ZoneInfo("UTC")
    return _zone


def _parse(value: str) -> date | datetime:
    """A date ("2026-10-03") or a time ("2026-10-03T09:00", with or without an offset), naive times in the user's zone"""
    value = value.strip()
    if len(value) == 10:
        return date.fromisoformat(value)
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo = zone())


def _instant(value: date | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time(), zone())


def _shown(stamp: dict[str, Any]) -> str:
    if "date" in stamp:
        return stamp["date"]
    moment = datetime.fromisoformat(stamp["dateTime"].replace("Z", "+00:00")).astimezone(zone())
    return moment.strftime("%Y-%m-%d %H:%M")


def describe(event: dict[str, Any], calendar_name: str | None = None) -> str:
    start, end = event.get("start") or {}, event.get("end") or {}
    when = f"{_shown(start)} → {_shown(end)}" if start and end else "(no time)"
    if "date" in start:
        when += " (all day)"
    lines = [f"- {event.get('summary') or '(no title)'} · {when} · id {event['id']}"]
    details: list[str] = []
    if calendar_name:
        details.append(f"calendar: {calendar_name}")
    if location := event.get("location"):
        details.append(f"where: {location}")
    if meet := event.get("hangoutLink"):
        details.append(f"meet: {meet}")
    if organizer := (event.get("organizer") or {}).get("email"):
        if not (event.get("organizer") or {}).get("self"):
            details.append(f"organizer: {organizer}")
    attendees = event.get("attendees") or []
    if attendees:
        listed = ", ".join(f"{a.get('email')} ({a.get('responseStatus', '?')})" for a in attendees[:15])
        more = f" and {len(attendees) - 15} more" if len(attendees) > 15 else ""
        details.append(f"attendees: {listed}{more}")
        if me := next((a for a in attendees if a.get("self")), None):
            details.append(f"the user's answer: {me.get('responseStatus')}")
    if event.get("recurringEventId"):
        details.append(f"repeats (series {event['recurringEventId']})")
    if description := " ".join((event.get("description") or "").split()):
        cut = description[:DESCRIPTION_CHARS] + ("…" if len(description) > DESCRIPTION_CHARS else "")
        details.append(f"notes: {cut}")
    if link := event.get("htmlLink"):
        details.append(link)
    return "\n".join([*lines, *(f"  {detail}" for detail in details)])


def calendars() -> list[dict[str, Any]]:
    data = call("GET", f"{CALENDAR_URL}/users/me/calendarList",
                {"fields": "items(id,summary,summaryOverride,primary,accessRole,selected,timeZone)", "maxResults": 250})
    return data.get("items") or []


def access_role(calendar: str) -> str:
    """The user's role on a calendar: owner, writer, reader or freeBusyReader"""
    path = f"{CALENDAR_URL}/users/me/calendarList/{quote(calendar or 'primary', safe = '')}"
    return (call("GET", path, {"fields": "accessRole"}) or {}).get("accessRole") or ""



# ---- Reading ----

def events(start: str | None, end: str | None, text: str | None, calendar: str, limit: int) -> str:
    begin = _instant(_parse(start)) if start else datetime.now(zone())
    last = _parse(end) if end else None
    finish = _instant(last) if last is not None else begin + timedelta(days = DEFAULT_DAYS)
    if last is not None and not isinstance(last, datetime):
        # An end date includes that whole day
        finish += timedelta(days = 1)
    params: dict[str, Any] = {
        "timeMin": begin.isoformat(),
        "timeMax": finish.isoformat(),
        "q": text,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": limit,
        "timeZone": str(zone()),
    }

    if calendar == "all":
        sources = [(item["id"], item.get("summaryOverride") or item.get("summary") or item["id"])
                   for item in calendars() if item.get("selected") or item.get("primary")][:MAX_CALENDARS]
    else:
        sources = [(calendar or "primary", None)]

    found: list[tuple[str, dict[str, Any], str | None]] = []
    for calendar_id, calendar_name in sources:
        data = call("GET", f"{_calendar_path(calendar_id)}/events", params)
        for event in data.get("items") or []:
            if event.get("status") == "cancelled":
                continue
            stamp = event.get("start") or {}
            key = stamp.get("dateTime") or stamp.get("date") or ""
            sort_key = _instant(_parse(key)).isoformat() if key else ""
            found.append((sort_key, event, calendar_name))
    found.sort(key = lambda item: item[0])
    found = found[:limit]

    span = f"{begin.strftime('%Y-%m-%d %H:%M')} to {finish.strftime('%Y-%m-%d %H:%M')} ({zone()})"
    if not found:
        return f"No events from {span}" + (f" matching {text!r}." if text else ".")
    lines = [f"{len(found)} event(s) from {span}, times in {zone()}:"]
    lines += [describe(event, name) for _, event, name in found]
    if calendar == "all":
        lines += ["", "Calendars read: " + ", ".join(f"{name} ({cid})" for cid, name in sources)]
    return "\n".join(lines)



# ---- Changing ----

def _stamp(value: date | datetime) -> dict[str, Any]:
    if isinstance(value, datetime):
        return {"dateTime": value.isoformat(), "timeZone": str(zone())}
    return {"date": value.isoformat()}


def _times(start: str | None, end: str | None, all_day: bool | None) -> dict[str, Any]:
    """start and end for an event body, filling in an end an hour (or a day) after the start"""
    fields: dict[str, Any] = {}
    if not start:
        if end:
            fields["end"] = _stamp(_parse(end))
        return fields
    begin = _parse(start)
    if all_day and isinstance(begin, datetime):
        begin = begin.date()
    if end:
        finish = _parse(end)
        if all_day and isinstance(finish, datetime):
            finish = finish.date()
        if not isinstance(finish, datetime) and not isinstance(begin, datetime):
            # Google's all-day end date is exclusive; the model means the last day of the event
            finish = finish + timedelta(days = 1)
    else:
        finish = begin + (timedelta(hours = 1) if isinstance(begin, datetime) else timedelta(days = 1))
    return {"start": _stamp(begin), "end": _stamp(finish)}


def _moved(event: dict[str, Any], begin: date | datetime, all_day: bool | None) -> dict[str, Any]:
    """start and end for `event` moved to `begin`, as long as it was"""
    old_start, old_end = event.get("start") or {}, event.get("end") or {}
    if all_day and isinstance(begin, datetime):
        begin = begin.date()
    if "date" in old_start and "date" in old_end and not isinstance(begin, datetime):
        length = date.fromisoformat(old_end["date"]) - date.fromisoformat(old_start["date"])
    elif "dateTime" in old_start and "dateTime" in old_end and isinstance(begin, datetime):
        length = (datetime.fromisoformat(old_end["dateTime"].replace("Z", "+00:00"))
                  - datetime.fromisoformat(old_start["dateTime"].replace("Z", "+00:00")))
    else:
        # Switching between all-day and timed: an hour, or a day
        return _times(begin.isoformat(), None, all_day)
    return {"start": _stamp(begin), "end": _stamp(begin + length)}


def edit(
    action: str,
    calendar: str,
    event_id: str | None,
    summary: str | None,
    start: str | None,
    end: str | None,
    all_day: bool | None,
    location: str | None,
    description: str | None,
    attendees: list[str] | None,
    add_meet: bool,
    recurrence: list[str] | None,
    response: str | None,
    send_updates: str,
    text: str | None,
) -> str:
    path = f"{_calendar_path(calendar)}/events"
    notify = {"sendUpdates": send_updates}

    if action == "quick_add":
        if not text:
            raise ValueError("quick_add needs text, e.g. \"Lunch with Sam tomorrow at noon\"")
        created = call("POST", f"{path}/quickAdd", {"text": text, **notify})
        return f"Added:\n{describe(created)}"

    body: dict[str, Any] = {}
    if summary is not None:
        body["summary"] = summary
    if location is not None:
        body["location"] = location
    if description is not None:
        body["description"] = description
    if attendees is not None:
        body["attendees"] = [{"email": email.strip()} for email in attendees if email.strip()]
    if recurrence is not None:
        body["recurrence"] = recurrence
    body.update(_times(start, end, all_day))
    query: dict[str, Any] = dict(notify)
    if add_meet:
        body["conferenceData"] = {"createRequest": {"requestId": uuid.uuid4().hex,
                                                    "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
        query["conferenceDataVersion"] = 1

    if action == "create":
        if "start" not in body:
            raise ValueError("create needs a start")
        body.setdefault("summary", "(no title)")
        created = call("POST", path, query, body)
        return f"Created:\n{describe(created)}"

    if not event_id:
        raise ValueError(f"{action} needs the event's id, from google_calendar_events")
    event_path = f"{path}/{quote(event_id, safe = '')}"
    match action:
        case "update":
            if not body:
                raise ValueError("update needs something to change")
            if start and not end:
                # A new start alone moves the event, keeping how long it is
                body.update(_moved(call("GET", event_path, {"fields": "start,end"}), _parse(start), all_day))
            return f"Updated:\n{describe(call('PATCH', event_path, query, body))}"
        case "delete":
            call("DELETE", event_path, notify)
            return f"Deleted the event {event_id}."
        case "respond":
            if response not in ("accepted", "declined", "tentative"):
                raise ValueError("respond needs response: accepted, declined or tentative")
            event = call("GET", event_path, {"fields": "attendees"})
            people = event.get("attendees") or []
            if not any(person.get("self") for person in people):
                raise ValueError("The user isn't invited to that event, so there's nothing to answer")
            for person in people:
                if person.get("self"):
                    person["responseStatus"] = response
            answered = call("PATCH", event_path, notify, {"attendees": people})
            return f"Answered {response}:\n{describe(answered)}"
    raise ValueError(f"Unknown action {action!r}")
