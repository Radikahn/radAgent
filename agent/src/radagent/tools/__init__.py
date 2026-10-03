from typing import Any

from radagent.tools.links import share_links
from radagent.tools.maps import find_places
from radagent.tools.web import read_page

# Custom tools handed to the agent alongside the harness built-ins; add new tools here to wire them in
TOOLS: list[Any] = [read_page, find_places, share_links]

__all__ = ["TOOLS"]
