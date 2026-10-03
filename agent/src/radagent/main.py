import argparse
from dotenv import load_dotenv
from pathlib import Path

from os import getenv


def _system_prompt() -> str:
    """The secret prompt when SECRET_PROMPT_PATH names one, otherwise the default system prompt"""
    from radagent.prompts.lib.prompt import initalize_agent

    secret_prompt_path = getenv("SECRET_PROMPT_PATH")
    return initalize_agent(override_prompt_path = Path(secret_prompt_path)) if secret_prompt_path else initalize_agent()


def main() -> None:
    parser = argparse.ArgumentParser(prog = "radagent")
    parser.add_argument("--repl", action = "store_true", help = "Start an interactive REPL for testing the agent")
    parser.add_argument("--serve", action = "store_true", help = "Serve the apps over a WebSocket on /ws (AgentCore Runtime's contract)")
    parser.add_argument("--host", default = None, help = "Where --serve listens; default 127.0.0.1, or 0.0.0.0 in a container")
    parser.add_argument("--port", type = int, default = 8080, help = "Where --serve listens")
    parser.add_argument("--model", default = None, help = "Override the model ID defined in config.py")
    args = parser.parse_args()

    load_dotenv()
    if args.repl:
        from radagent.repl import run_repl
        run_repl(model = args.model, system_prompt = _system_prompt())
    elif args.serve:
        # On AWS the keys and the secret prompt come from Secrets Manager, and have to be in place before the agent's
        # modules read the environment
        from radagent.server.settings import load_secrets
        load_secrets()
        from radagent.server.app import run_server
        run_server(model = args.model, system_prompt = _system_prompt(), host = args.host, port = args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
