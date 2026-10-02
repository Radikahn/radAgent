import argparse
from dotenv import load_dotenv
from pathlib import Path
from radagent.prompts.lib.prompt import initalize_agent

from os import getenv


load_dotenv()
SECRET_PROMPT_PATH = getenv("SECRET_PROMPT_PATH")
print(f"Secret Path: {SECRET_PROMPT_PATH}")
# Fall back to the default system prompt when no secret prompt is configured
SYSTEM_PROMPT: str = (
    initalize_agent(override_prompt_path = Path(SECRET_PROMPT_PATH))
    if SECRET_PROMPT_PATH else initalize_agent()
)

def main() -> None:
    parser = argparse.ArgumentParser(prog = "radagent")
    parser.add_argument("--repl", action = "store_true", help = "Start an interactive REPL for testing the agent")
    parser.add_argument("--model", default = None, help = "Override the model ID defined in config.py")
    args = parser.parse_args()

    if args.repl:
        from radagent.repl import run_repl
        run_repl(model = args.model, system_prompt = SYSTEM_PROMPT)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
