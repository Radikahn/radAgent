"""
Connecting Google from the apps' settings; see radagent.tools.google.account for where the login is kept

Commands:
    {"type": "google_status"}
    {"type": "google_connect", "code": str, "verifier": str, "redirect_uri": str, "client_id": str}
        the authorization code the app got back from Google's consent page, and the PKCE verifier it made for it
    {"type": "google_disconnect"}

Event: {"type": "google", "connected": bool, "email"?: str, "connected_at"?: str, "missing"?: [scope], "error"?: str}
to the client that asked for the status or whose connect failed, and to every client when the login changes, so each
device's settings stay current
"""
import asyncio
from typing import TYPE_CHECKING, Any

from radagent.tools.google import account
from radagent.tools.google.client import GoogleError

if TYPE_CHECKING:
    from radagent.server.core import Client, Hub

COMMANDS: frozenset[str] = frozenset({"google_status", "google_connect", "google_disconnect"})

# Running commands, kept so they aren't collected before they finish
_running: set[asyncio.Task[None]] = set()



async def _handle(hub: "Hub", client: "Client", command: dict[str, Any]) -> None:
    kind = command.get("type")
    try:
        if kind == "google_status":
            client.send("google", **await asyncio.to_thread(account.status))
            return
        if kind == "google_connect":
            fields = [str(command.get(name) or "") for name in ("code", "verifier", "redirect_uri", "client_id")]
            await asyncio.to_thread(account.connect, *fields)
        else:
            await asyncio.to_thread(account.disconnect)
    except GoogleError as e:
        client.send("google", **await asyncio.to_thread(account.status), error = str(e))
        return
    except Exception as e:
        client.send("google", **await asyncio.to_thread(account.status), error = f"{type(e).__name__}: {e}")
        return
    hub.send("google", **await asyncio.to_thread(account.status))


def handle(hub: "Hub", client: "Client", command: dict[str, Any]) -> None:
    """Carry out a google_* command; Google and Secrets Manager are slow, so it runs on its own"""
    task = asyncio.create_task(_handle(hub, client, command))
    _running.add(task)
    task.add_done_callback(_running.discard)
