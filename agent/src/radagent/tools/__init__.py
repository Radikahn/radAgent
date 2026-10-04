from typing import Any

from radagent.tools.google import GOOGLE_TOOLS
from radagent.tools.links import share_links
from radagent.tools.maps import find_places
from radagent.tools.sandbox import SANDBOX_TOOLS
from radagent.tools.spotify import SPOTIFY_TOOLS
from radagent.tools.web import read_page
from radagent.tools.youtube import search_youtube

# Custom tools handed to the agent alongside the harness built-ins; add new tools here to wire them in
TOOLS: list[Any] = [
    read_page,
    find_places,
    share_links,
    search_youtube,
    *SPOTIFY_TOOLS,
    *GOOGLE_TOOLS,
    *SANDBOX_TOOLS,
]

__all__ = ["TOOLS"]
