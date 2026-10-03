"""
`radagent --spotify-login`: connect the agent to the user's Spotify account, again every 6 months

Runs Spotify's authorization code flow on this machine: opens the consent page in the browser, catches the redirect on
a loopback port, trades the code for a refresh token and saves it to agent/.env as SPOTIFY_REFRESH_TOKEN. The local
agent reads it from there and scripts/put-secrets.sh sends it to AWS. The token itself is never printed
"""
import json
import os
import secrets
import socket
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from dotenv import set_key

from radagent.tools.spotify.client import API_URL, TIMEOUT_S, SpotifyError, token_request


AUTHORIZE_URL: str = "https://accounts.spotify.com/authorize"
# Spotify only takes plain http redirects to a loopback IP (not "localhost"); add this one to the app's settings
DEFAULT_REDIRECT_URI: str = "http://127.0.0.1:8888/callback"
LOGIN_TIMEOUT_S: int = 300

# Everything the spotify tools touch
SCOPES: tuple[str, ...] = (
    "user-read-private",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-read-playback-position",
    "user-top-read",
    "user-library-read",
    "user-library-modify",
    "user-follow-read",
    "user-follow-modify",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
)

# agent/.env, where load_dotenv and scripts/put-secrets.sh look; this file is agent/src/radagent/tools/spotify/login.py
_AGENT_DIR = Path(__file__).resolve().parents[4]
ENV_FILE: Path = (_AGENT_DIR if (_AGENT_DIR / "pyproject.toml").exists() else Path.cwd()) / ".env"



class _IPv6Server(HTTPServer):
    address_family = socket.AF_INET6



def _page(title: str, detail: str) -> bytes:
    return (f"<!doctype html><meta charset=utf-8><title>{title}</title>"
            f"<body style='font:16px system-ui;margin:4rem auto;max-width:32rem'><h1>{title}</h1><p>{detail}</p>").encode()


def _wait_for_redirect(redirect_uri: str, state: str) -> dict[str, str]:
    """Serve the redirect URI until Spotify sends the browser back to it; returns the query it carried"""
    target = urlsplit(redirect_uri)
    result: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlsplit(self.path)
            if request.path != (target.path or "/"):
                self.send_error(404)
                return
            params = {key: values[0] for key, values in parse_qs(request.query).items()}
            if params.get("state") != state:
                # Not the request this login started, so it can't be trusted to carry the user's code
                self.send_error(400, "Unexpected state")
                return
            result.update(params)
            ok = "code" in params
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_page("Spotify is connected", "You can close this tab.") if ok else
                             _page("Spotify login failed", f"Spotify said: {params.get('error', 'no code')}."))

        def log_message(self, format: str, *args: object) -> None:
            pass

    server_class = _IPv6Server if target.hostname == "::1" else HTTPServer
    with server_class((target.hostname or "127.0.0.1", target.port or 80), Callback) as server:
        server.timeout = 1
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        while not result and time.monotonic() < deadline:
            server.handle_request()
    return result


def login() -> int:
    """Run the login; returns the exit status"""
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI
    if not client_id or not client_secret:
        print(
            "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in agent/.env first. They're on your app's page at\n"
            "https://developer.spotify.com/dashboard (create one with the Web API if you have none), where\n"
            f"{redirect_uri} also has to be listed under Redirect URIs.",
            file = sys.stderr,
        )
        return 1
    target = urlsplit(redirect_uri)
    if target.scheme != "http" or target.hostname not in ("127.0.0.1", "::1") or not target.port:
        print(f"SPOTIFY_REDIRECT_URI must be http://127.0.0.1:<port>/<path> for this login, not {redirect_uri}",
              file = sys.stderr)
        return 1

    state = secrets.token_urlsafe(24)
    url = AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        # Always ask, so a login with new scopes isn't skipped over by an older consent
        "show_dialog": "true",
    })
    print(f"Opening Spotify in your browser. If nothing opens, go to:\n\n  {url}\n")
    webbrowser.open(url)

    try:
        result = _wait_for_redirect(redirect_uri, state)
    except OSError as e:
        print(f"Couldn't listen on {target.hostname}:{target.port} ({e}). Set SPOTIFY_REDIRECT_URI to another port "
              f"and add it to the app's Redirect URIs.", file = sys.stderr)
        return 1
    if "code" not in result:
        problem = result.get("error") or f"no answer within {LOGIN_TIMEOUT_S // 60} minutes"
        print(f"Spotify login failed: {problem}", file = sys.stderr)
        return 1

    try:
        tokens = token_request(
            {"grant_type": "authorization_code", "code": result["code"], "redirect_uri": redirect_uri},
            client_id,
            client_secret,
        )
    except SpotifyError as e:
        print(f"Spotify login failed: {e}", file = sys.stderr)
        return 1
    if not tokens.get("refresh_token"):
        print("Spotify didn't return a refresh token.", file = sys.stderr)
        return 1

    if not ENV_FILE.exists():
        ENV_FILE.touch(mode = 0o600)
    set_key(str(ENV_FILE), "SPOTIFY_REFRESH_TOKEN", tokens["refresh_token"])

    account = "your account"
    try:
        request = Request(f"{API_URL}/me", headers = {"Authorization": f"Bearer {tokens['access_token']}"})
        with urlopen(request, timeout = TIMEOUT_S) as response:
            account = json.load(response).get("display_name") or account
    except Exception:
        pass
    print(
        f"Connected Spotify as {account} and saved SPOTIFY_REFRESH_TOKEN to {ENV_FILE}.\n"
        "For the deployed agent, run scripts/put-secrets.sh; new chats pick it up.\n"
        "Spotify logins last 6 months, so run this again before then."
    )
    return 0
