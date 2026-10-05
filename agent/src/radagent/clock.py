"""
The user's own date and time, in a note ahead of every message, so "today" and "this week" mean the user's day

The model doesn't know the date, and on AWS the agent runs in UTC, so without this it guesses from its training data
or takes the server's day for the user's. The app sends its IANA time zone with each prompt (`send` in
`client/src/agent.ts`); the time comes from this machine's clock. Like /code's note it's a block of its own ahead of
the message, which server/history.py hides again and memory leaves out. It goes in the message rather than the system
prompt so the prompt stays cached from turn to turn, and each message carries its own: a chat reopened days later
still gets today's date
"""
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError



def user_zone(name: object) -> tzinfo:
    """
    The time zone `name` names, e.g. "America/Toronto"; this machine's when it's missing or unknown, which is the
    user's own in the REPL and UTC on AWS
    """
    if isinstance(name, str) and name:
        try:
            return ZoneInfo(name)
        # ValueError: a name that isn't a zone key at all, like "../etc"
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def time_note(zone: tzinfo, now: datetime | None = None) -> str:
    """
    Args:
        zone: {tzinfo} The user's time zone, see user_zone
        now: {datetime | None} The moment to describe; defaults to now
    """
    local = (now or datetime.now(zone)).astimezone(zone)
    offset = local.strftime("%z")
    name = getattr(zone, "key", None) or local.tzname() or "UTC"
    return (
        f"<current_time>It's {local:%A %Y-%m-%d %H:%M} for the user as they send this message, in their time zone "
        f"{name} (UTC{offset[:3]}:{offset[3:]}). Work out today, tomorrow, this week and other relative dates from "
        "this, not from what you know or from earlier in the conversation.</current_time>"
    )


def is_time_note(text: str) -> bool:
    return text.startswith("<current_time>")
