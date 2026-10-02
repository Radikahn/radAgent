import readline  # noqa: F401 -- enables arrow-key history and line editing in input()

from radagent.agent import RadAgent
from radagent.repl.display import ReplCallbackHandler

HELP_TEXT = """Commands:
  /help   Show this message
  /reset  Start a fresh agent (clears conversation)
  /exit   Quit the REPL (also /quit or Ctrl-D)"""


def run_repl(model: str | None = None, system_prompt: str | None = None) -> None:
    """
    Interactive loop for testing RadAgent from the terminal

    Args:
        model: {str | None} Override the default model defined in `config.py`
        system_prompt: {str | None} Override the default system prompt
    """
    display = ReplCallbackHandler()

    def new_agent() -> RadAgent:
        if system_prompt is None:
            return RadAgent(model = model, callback_handler = display)
        return RadAgent(model = model, system_prompt = system_prompt, callback_handler = display)

    agent = new_agent()
    print("radAgent REPL. Type /help for commands.")

    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not query:
            continue

        if query in ("/exit", "/quit"):
            break
        if query == "/help":
            print(HELP_TEXT)
            continue
        if query == "/reset":
            agent = new_agent()
            print("Agent reset.")
            continue

        display.start_turn()
        try:
            # The display handler streams the labelled response to stdout
            agent.query(query)
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}")
        finally:
            display.end_turn()
