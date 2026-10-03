from typing import Any

from radagent.tools.google.tools import (
    google_api,
    google_calendar_edit,
    google_calendar_events,
    google_docs_create,
    google_docs_edit,
    google_drive_edit,
    google_drive_read,
    google_drive_search,
)

# The Google suite, which acts through the account connected in the app's settings: finding and reading first, then
# changes, then the raw API
GOOGLE_TOOLS: list[Any] = [
    google_drive_search,
    google_drive_read,
    google_calendar_events,
    google_drive_edit,
    google_docs_create,
    google_docs_edit,
    google_calendar_edit,
    google_api,
]

__all__ = ["GOOGLE_TOOLS"]
