# radagent

A Python Strands agent baseline that is meant to be modded.

```sh
uv sync
uv run radagent --repl                 # chat in the terminal
uv run radagent --dev                  # serve the app over a WebSocket on 127.0.0.1:8787
```

`--serve` speaks AgentCore Runtime's contract (`/ws`, `/ping`, `/invocations`; see `src/radagent/server/app.py`).
The `Dockerfile` builds the linux/arm64 image the runtime runs, which serves on port 8080; `scripts/deploy-agent.sh`
builds, pushes and deploys it.

## Spotify

The `spotify_*` tools search Spotify, read the library, control playback and edit playlists as you. They act
through a Spotify app of your own, in Development Mode, which needs Spotify Premium on the account that owns it:

1. Create an app at <https://developer.spotify.com/dashboard> with the Web API, and add
   `http://127.0.0.1:8888/callback` to its Redirect URIs (Spotify takes `127.0.0.1`, not `localhost`).
2. Put its `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `agent/.env`.
3. `uv run radagent --spotify-login` opens Spotify's consent page and saves `SPOTIFY_REFRESH_TOKEN` to `agent/.env`.
   Set `SPOTIFY_REDIRECT_URI` if port 8888 is taken (and register that URI instead).
4. For the deployed agent, `scripts/put-secrets.sh`; new chats pick the keys up.

Spotify logins last 6 months; when one runs out the tools say so, and steps 3 and 4 renew it. Development Mode also
caps search at 10 results per type and only lists the songs of playlists you own or collaborate on. Spotify results
count as untrusted web content (playlist names and descriptions are anyone's to write), so like YouTube searches they
switch off shell and file editing for the rest of the chat.

## Sandbox

The `sandbox_*` tools run commands, manage background jobs, edit files and move files to and from a container on your
own server, over SSH with asyncssh (`src/radagent/tools/sandbox`). They read `SANDBOX_HOST`, `SANDBOX_PORT`,
`SANDBOX_HOST_KEY`, `SANDBOX_SSH_KEY_PATH` (or `SANDBOX_SSH_KEY`) and, through a Cloudflare Tunnel,
`SANDBOX_CF_ACCESS_CLIENT_ID` and `SANDBOX_CF_ACCESS_CLIENT_SECRET`; `../sandbox/keygen.sh` makes the key and prints
the rest. Setting up the server is in [../sandbox/README.md](../sandbox/README.md). Like `shell`, the tools turn off for
the rest of a chat once it reads untrusted web content.

