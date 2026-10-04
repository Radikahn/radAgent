---
name: add-secret
description: Give the radagent agent a new API key, token or other secret, locally and on AWS. Use when a tool or feature needs credentials (e.g. a new third-party API).
---

# Adding a secret the agent reads

Locally the agent reads `agent/.env` (`load_dotenv()`); on AWS, `server/settings.py` loads one Secrets Manager
JSON object into the environment at startup. Code just reads `os.getenv("X_API_KEY")`.

1. Read it with `os.getenv` at call time, not import time, and tell the model plainly when it's missing (an error
   result naming the env var and the README section), so the rest of the agent works without it.
2. `scripts/put-secrets.sh`: add the name to `env_keys=(...)` and to the header comment. Values go to `jq` through
   the environment, never argv, and are never printed.
3. `infra/secrets.tf`: add the name to the comment listing what the secret holds. No Terraform resource change:
   the value never goes through Terraform.
4. `infra/README.md`: the `put-secrets.sh` line in the setup steps lists the keys.
5. `agent/README.md`: how to obtain the key (and any login flow, like `--spotify-login` in `main.py`).
6. Running AgentCore sessions keep the environment they started with (up to 8 h). If the key must work right after
   `put-secrets.sh`, re-read it with `server.settings.read_secret()` on a missing/refused key, throttled (see
   `tools/spotify/client.py`, commit `c3aea39`).

Tokens a user grants at runtime (OAuth refresh tokens) are a different case: the agent stores them itself, locally
under `agent/.agent/` with mode 600 and on AWS in a dedicated secret only the runtime role can read and write
(`infra/iam.tf`, least privilege). Keep such files away from the file tools (`_PROTECTED_NAMES` /
`_PROTECTED_ROOTS` in `trust_gate.py`).

Never commit a value, add one to `.env.development`, or log one. `.env` is gitignored.
