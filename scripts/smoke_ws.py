"""
Smoke test for the agent's WebSocket, locally or on AgentCore Runtime

    uv run --project agent python scripts/smoke_ws.py                         # ws://127.0.0.1:8787/ws, no auth
    uv run --project agent python scripts/smoke_ws.py --remote                # the deployed runtime; asks for your
                                                                              # Cognito email and password
    ... --prompt "Say hi in five words"                                       # costs a few Bedrock tokens
    ... --prompt "Count to 20 slowly" --drop                                  # disconnect mid-turn, reconnect and
                                                                              # check the finished turn was saved

Speaks the same framing as the apps: events arrive as JSON arrays, and a large one as {"type": "part", ...} pieces
"""
import argparse
import asyncio
import base64
import getpass
import json
import subprocess
import sys
import time
import uuid
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

import boto3
import websockets

BEARER_PROTOCOL = "base64UrlBearerAuthorization"



def terraform_output(name: str) -> str:
    return subprocess.run(
        ["terraform", "-chdir=infra", "output", "-raw", name], check = True, capture_output = True, text = True
    ).stdout.strip()


def sign_in(region: str, client_id: str) -> str:
    """A Cognito access token for the app client"""
    email = input("Cognito email: ").strip()
    password = getpass.getpass("Password: ")
    cognito = boto3.client("cognito-idp", region_name = region)
    result = cognito.initiate_auth(
        ClientId = client_id, AuthFlow = "USER_PASSWORD_AUTH", AuthParameters = {"USERNAME": email, "PASSWORD": password}
    )
    if challenge := result.get("ChallengeName"):
        if challenge != "SOFTWARE_TOKEN_MFA":
            sys.exit(f"Unexpected challenge {challenge}; finish setting up the user first")
        code = input("MFA code: ").strip()
        result = cognito.respond_to_auth_challenge(
            ClientId = client_id, ChallengeName = challenge, Session = result["Session"],
            ChallengeResponses = {"USERNAME": email, "SOFTWARE_TOKEN_MFA_CODE": code},
        )
    return result["AuthenticationResult"]["AccessToken"]


def claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))



class Events:
    """Unpacks batched and split messages into events"""

    def __init__(self, socket: Any) -> None:
        self.socket = socket
        self.parts: dict[str, list[str | None]] = {}
        self.queue: list[dict[str, Any]] = []
        self.messages = 0
        self.largest = 0
        self.split = 0


    async def next(self, timeout: float = 120) -> dict[str, Any]:
        while not self.queue:
            raw = await asyncio.wait_for(self.socket.recv(), timeout)
            self.messages += 1
            self.largest = max(self.largest, len(raw.encode() if isinstance(raw, str) else raw))
            data = json.loads(raw)
            if isinstance(data, list):
                self.queue.extend(data)
            elif isinstance(data, dict) and data.get("type") == "part":
                slices = self.parts.setdefault(data["id"], [None] * data["of"])
                slices[data["n"]] = data["data"]
                if all(piece is not None for piece in slices):
                    self.split += 1
                    self.queue.append(json.loads("".join(slices)))  # type: ignore[arg-type]
                    del self.parts[data["id"]]
            else:
                self.queue.append(data)
        return self.queue.pop(0)


    async def until(self, kind: str, timeout: float = 120, **match: Any) -> dict[str, Any]:
        while True:
            event = await self.next(timeout)
            if event.get("type") == "error":
                print(f"  ! error: {event.get('message')}")
            if event.get("type") == kind and all(event.get(key) == value for key, value in match.items()):
                return event



async def run(args: argparse.Namespace) -> None:
    subprotocols: list[str] | None = None
    ping_url: str | None = None
    if args.remote:
        region, arn, client_id = terraform_output("region"), terraform_output("runtime_arn"), terraform_output("client_id")
        token = sign_in(region, client_id)
        session = f"radagent-{claims(token)['sub']}"
        url = (
            f"wss://bedrock-agentcore.{region}.amazonaws.com/runtimes/{quote(arn, safe = '')}/ws"
            f"?X-Amzn-Bedrock-AgentCore-Runtime-Session-Id={session}"
        )
        encoded = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")
        subprotocols = [f"{BEARER_PROTOCOL}.{encoded}", BEARER_PROTOCOL]
    else:
        url = args.url
        ping_url = url.replace("ws://", "http://").replace("/ws", "/ping")

    def connect() -> Any:
        return websockets.connect(url, subprotocols = subprotocols, max_size = None, open_timeout = 120)  # type: ignore[arg-type]

    chat = args.chat or uuid.uuid4().hex[:12]
    started = time.monotonic()
    async with connect() as socket:
        events = Events(socket)
        await events.until("ready")
        listed = await events.until("chats")
        print(f"connected in {time.monotonic() - started:.1f}s; {len(listed['chats'])} chats; subprotocol {socket.subprotocol!r}")

        await socket.send(json.dumps({"type": "open", "chat": chat}))
        history = await events.until("history", chat = chat)
        print(f"history of {chat}: {len(history['turns'])} turns, running={history.get('running')}")

        if not args.prompt:
            print(f"framing: {events.messages} messages, largest {events.largest} bytes, {events.split} joined from parts")
            return

        turn = str(uuid.uuid4())
        await socket.send(json.dumps({"type": "prompt", "chat": chat, "turn": turn, "text": args.prompt, "command": None}))
        await events.until("turn_start", turn = turn)
        print("> " + args.prompt)
        while True:
            event = await events.next()
            if event.get("turn") != turn:
                continue
            if event["type"] == "text":
                print(event["delta"], end = "", flush = True)
                if args.drop:
                    if ping_url:
                        print(f"\n[ping while answering: {json.load(urlopen(ping_url))['status']}]")
                    print("[dropping the connection mid-turn]")
                    break
            elif event["type"] in ("tool_start", "tool_end"):
                print(f"\n[{event['type']} {event.get('name', event.get('status', ''))}]", end = "")
            elif event["type"] == "turn_end":
                print(f"\n[turn_end {event['stop_reason']}]")
                break
        print(f"framing: {events.messages} messages, largest {events.largest} bytes, {events.split} joined from parts")

    if not args.drop:
        return
    # The turn carries on without us; come back, and wait for it to land in the saved history
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        async with connect() as socket:
            events = Events(socket)
            await events.until("ready")
            await socket.send(json.dumps({"type": "open", "chat": chat}))
            history = await events.until("history", chat = chat)
            if not history.get("running"):
                last = history["turns"][-1] if history["turns"] else {}
                text = "".join(part.get("text", "") for part in last.get("parts", []) if part.get("kind") == "text")
                print(f"reconnected: {len(history['turns'])} turns saved; last answer: {text[:200]!r}")
                if ping_url:
                    print(f"ping after the turn: {json.load(urlopen(ping_url))['status']}")
                return
            print("reconnected: still answering…")
    sys.exit("the turn never finished")


def main() -> None:
    parser = argparse.ArgumentParser(description = __doc__, formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", nargs = "?", default = "ws://127.0.0.1:8787/ws")
    parser.add_argument("--remote", action = "store_true", help = "Use the deployed runtime (terraform outputs + Cognito)")
    parser.add_argument("--prompt", help = "Send this prompt and stream the answer")
    parser.add_argument("--chat", help = "Chat id ([a-z0-9]{6,32}); a new one by default")
    parser.add_argument("--drop", action = "store_true", help = "With --prompt, disconnect mid-answer and reconnect")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
