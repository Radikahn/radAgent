"""
Settings the agent takes from AWS when it runs there, loaded before anything reads the environment

The secret named by RADAGENT_SECRET_ID (see infra/secrets.tf, filled by scripts/put-secrets.sh) is a JSON object.
SECRET_PROMPT is the system prompt that agent/.env points at with SECRET_PROMPT_PATH locally; every other key becomes
an environment variable, e.g. EXA_API_KEY. Variables already set win, so a local run can override any of them. The
served agent only uses the prompt to fill the first prompt preset when there are none yet (radagent.prompts.presets)
"""
import json
import os
import sys
import tempfile
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def read_secret() -> dict[str, Any] | None:
    """The agent's secret as it is now; None without RADAGENT_SECRET_ID, or when it can't be read"""
    secret_id = os.getenv("RADAGENT_SECRET_ID")
    if not secret_id:
        return None
    try:
        value = boto3.client("secretsmanager").get_secret_value(SecretId = secret_id)["SecretString"]
        settings = json.loads(value)
    except (BotoCoreError, ClientError, KeyError, ValueError) as e:
        # A secret without a value yet still leaves a working agent, just without its keys and its own prompt
        print(f"[radagent] couldn't load the secret {secret_id}: {type(e).__name__}: {e}", file = sys.stderr)
        return None
    if not isinstance(settings, dict):
        print(f"[radagent] the secret {secret_id} isn't a JSON object; ignoring it", file = sys.stderr)
        return None
    return settings


def load_secrets() -> None:
    """Put the agent's secret into the environment; does nothing without RADAGENT_SECRET_ID"""
    settings = read_secret()
    if settings is None:
        return

    prompt = settings.pop("SECRET_PROMPT", None)
    for name, setting in settings.items():
        if isinstance(setting, str):
            os.environ.setdefault(name, setting)
    if isinstance(prompt, str) and prompt.strip() and "SECRET_PROMPT_PATH" not in os.environ:
        # mkstemp makes the file readable by this user only
        handle, path = tempfile.mkstemp(prefix = "radagent-prompt-", suffix = ".txt")
        with os.fdopen(handle, "w", encoding = "utf-8") as file:
            file.write(prompt)
        os.environ["SECRET_PROMPT_PATH"] = path
