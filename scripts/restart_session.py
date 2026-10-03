"""
Restart the agent's session on AgentCore Runtime, so the apps get the latest deploy and secrets

    uv run --project agent python scripts/restart_session.py      # asks for your Cognito email and password

Both apps connect to one session, radagent-<your user id>, and AgentCore keeps a session on the code and secrets it
started with until nothing has used it for 30 minutes. Stopping it makes the next message start a fresh one. Chats are
saved as they go, so nothing is lost, though a reply still being written is cut off. The runtime only takes Cognito
tokens, not AWS credentials (`aws bedrock-agentcore stop-runtime-session` gets "Authorization method mismatch"),
hence the sign-in
"""
import json
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from smoke_ws import claims, sign_in, terraform_output



def main() -> None:
    region, arn, client_id = terraform_output("region"), terraform_output("runtime_arn"), terraform_output("client_id")
    token = sign_in(region, client_id)
    session = f"radagent-{claims(token)['sub']}"
    request = Request(
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{quote(arn, safe = '')}/stopruntimesession"
        "?qualifier=DEFAULT",
        data = b"{}",
        method = "POST",
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session,
        },
    )
    try:
        with urlopen(request, timeout = 30) as response:
            json.load(response)
    except HTTPError as e:
        if e.code == 404:
            print("No session was running; the next message starts a fresh one.")
            return
        sys.exit(f"Couldn't stop {session}: HTTP {e.code} {e.read().decode(errors = 'replace')}")
    print(f"Stopped {session}. The next message from either app starts a fresh session with the latest deploy and "
          f"secrets.")


if __name__ == "__main__":
    main()
