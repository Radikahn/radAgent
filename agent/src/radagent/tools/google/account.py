"""
The user's Google login, which the app hands over when they press Connect Google in its settings

The app runs Google's consent page and sends the agent the authorization code it got back (with its PKCE verifier);
the agent trades it for a refresh token here and keeps it, so its tools work whichever device asked and while every
device sleeps. The token never goes back to the apps. It's kept as one JSON record:
    locally         in .agent/google.json, readable by this user only
    on AWS          in the Secrets Manager secret named by RADAGENT_GOOGLE_SECRET_ID (infra/secrets.tf), which the
                    runtime's role may read and write; scripts/put-secrets.sh never touches it

    {"client_id": str, "refresh_token": str, "scopes": [str], "email": str, "connected_at": ISO 8601}
"""
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit

from radagent.tools.google.client import (
    REVOKE_URL, SCOPES, GoogleError, GoogleNotConnected, forget_login, post_form, remember_login, token_request,
)


LOCAL_LOGIN: Path = Path(".agent/google.json")
# Google sends a native app back to its reversed client ID, e.g. com.googleusercontent.apps.123-abc:/oauth2redirect
_CLIENT_SUFFIX: str = ".apps.googleusercontent.com"



class Login(TypedDict):
    client_id: str
    refresh_token: str
    scopes: list[str]
    email: str
    connected_at: str



# ---- Where the login is kept ----

def _secret_id() -> str | None:
    return os.getenv("RADAGENT_GOOGLE_SECRET_ID") or None


def _secrets() -> Any:
    import boto3
    return boto3.client("secretsmanager")


def load() -> Login | None:
    """
    The saved login, or None when Google isn't connected

    Raises:
        GoogleError: The secret couldn't be read
    """
    if secret_id := _secret_id():
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            text = _secrets().get_secret_value(SecretId = secret_id)["SecretString"]
        except ClientError as e:
            # A secret that has never had a value has no AWSCURRENT version, which is what not connected looks like
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return None
            raise GoogleError(0, f"Couldn't read the Google login from {secret_id}: {e}") from None
        except (BotoCoreError, KeyError) as e:
            raise GoogleError(0, f"Couldn't read the Google login from {secret_id}: {e}") from None
    else:
        try:
            text = LOCAL_LOGIN.read_text(encoding = "utf-8")
        except FileNotFoundError:
            return None
    try:
        record = json.loads(text)
    except ValueError:
        print("[radagent] the saved Google login isn't JSON; treating Google as not connected", file = sys.stderr)
        return None
    if not isinstance(record, dict) or not record.get("refresh_token") or not record.get("client_id"):
        return None
    return Login(
        client_id = str(record["client_id"]),
        refresh_token = str(record["refresh_token"]),
        scopes = [str(scope) for scope in record.get("scopes") or []],
        email = str(record.get("email") or ""),
        connected_at = str(record.get("connected_at") or ""),
    )


def _store(record: dict[str, Any]) -> None:
    """Save `record`, which is {} to forget the login"""
    text = json.dumps(record)
    if secret_id := _secret_id():
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            _secrets().put_secret_value(SecretId = secret_id, SecretString = text)
        except (BotoCoreError, ClientError) as e:
            raise GoogleError(0, f"Couldn't save the Google login to {secret_id}: {e}") from None
        return
    if not record:
        LOCAL_LOGIN.unlink(missing_ok = True)
        return
    LOCAL_LOGIN.parent.mkdir(parents = True, exist_ok = True)
    temporary = LOCAL_LOGIN.with_name(LOCAL_LOGIN.name + ".tmp")
    # Created readable by this user only, then swapped in, so a crash never leaves half a login behind
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding = "utf-8") as file:
        file.write(text)
    os.replace(temporary, LOCAL_LOGIN)



# ---- Connecting and disconnecting ----

def _email(id_token: str | None) -> str:
    """The account's address from the ID token; it came straight from Google over TLS, so its claims aren't checked"""
    try:
        payload = (id_token or "").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return str(claims.get("email") or "")
    except (IndexError, ValueError):
        return ""


def _check_client(client_id: str, redirect_uri: str) -> None:
    expected = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if expected and client_id != expected:
        raise GoogleError(0, "The app used a different Google client than this agent is set up for (GOOGLE_CLIENT_ID).")
    if not client_id.endswith(_CLIENT_SUFFIX):
        raise GoogleError(0, f"{client_id!r} isn't a Google OAuth client ID.")
    scheme = "com.googleusercontent.apps." + client_id.removesuffix(_CLIENT_SUFFIX)
    if urlsplit(redirect_uri).scheme != scheme:
        raise GoogleError(0, f"The redirect has to go to the client's own scheme, {scheme}:/...")


def connect(code: str, verifier: str, redirect_uri: str, client_id: str) -> Login:
    """
    Trade the app's authorization code for a refresh token and save it, replacing any earlier login

    Raises:
        GoogleError: Google refused the code, or the login couldn't be saved
    """
    code, verifier, redirect_uri, client_id = (value.strip() for value in (code, verifier, redirect_uri, client_id))
    if not (code and verifier and redirect_uri and client_id):
        raise GoogleError(0, "Connecting Google needs the code, its verifier, the redirect URI and the client ID.")
    _check_client(client_id, redirect_uri)

    tokens = token_request({
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    })
    if not tokens.get("refresh_token"):
        raise GoogleError(0, "Google didn't hand out a refresh token; disconnect the app at "
                             "https://myaccount.google.com/connections and connect again.")

    granted = str(tokens.get("scope") or "").split()
    login = Login(
        client_id = client_id,
        refresh_token = tokens["refresh_token"],
        scopes = granted,
        email = _email(tokens.get("id_token")),
        connected_at = datetime.now(timezone.utc).isoformat(timespec = "seconds"),
    )
    previous = _safe_load()
    _store(dict(login))
    remember_login(login, tokens.get("access_token"), int(tokens.get("expires_in") or 0))
    if previous and previous["refresh_token"] != login["refresh_token"]:
        _revoke(previous["refresh_token"])
    return login


def disconnect() -> None:
    """
    Forget the login, and ask Google to revoke it so the token can't be used again

    Raises:
        GoogleError: The login couldn't be removed from where it's kept
    """
    login = _safe_load()
    _store({})
    forget_login()
    if login:
        _revoke(login["refresh_token"])


def _safe_load() -> Login | None:
    try:
        return load()
    except GoogleError:
        return None


def _revoke(token: str) -> None:
    try:
        post_form(REVOKE_URL, {"token": token})
    except GoogleError as e:
        # Already revoked or expired is as good as revoked
        print(f"[radagent] revoking the old Google login failed: {e}", file = sys.stderr)


def status() -> dict[str, Any]:
    """What the settings show: whether Google is connected, as whom, and which of the tools' scopes are missing"""
    try:
        login = load()
    except GoogleError as e:
        return {"connected": False, "error": str(e)}
    if not login:
        return {"connected": False}
    return {
        "connected": True,
        "email": login["email"],
        "connected_at": login["connected_at"],
        "missing": [scope for scope in SCOPES if scope not in login["scopes"]],
    }


__all__ = ["Login", "connect", "disconnect", "load", "status", "GoogleNotConnected"]
