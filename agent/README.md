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
