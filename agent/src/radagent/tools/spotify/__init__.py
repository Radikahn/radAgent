from typing import Any

from radagent.tools.spotify.tools import (
    spotify_api,
    spotify_library,
    spotify_lookup,
    spotify_now_playing,
    spotify_player,
    spotify_playlist,
    spotify_save,
    spotify_search,
)

# The Spotify suite: finding and reading first, then playback, then changes to the user's account
SPOTIFY_TOOLS: list[Any] = [
    spotify_search,
    spotify_library,
    spotify_lookup,
    spotify_now_playing,
    spotify_player,
    spotify_playlist,
    spotify_save,
    spotify_api,
]

__all__ = ["SPOTIFY_TOOLS"]
