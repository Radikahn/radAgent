import asyncio
import readline  # noqa: F401 -- enables arrow-key history and line editing in input()
import shlex

from radagent.agent import RadAgent
from radagent.commands import COMMANDS, CommandRun, parse_command
from radagent.media import Attachment, MediaError
from radagent.repl.display import ReplCallbackHandler, ResearchPrinter

HELP_TEXT = """Commands:
  /help   Show this message
  /reset  Start a fresh agent (clears conversation)
  /attach PATH...  Send files (images, PDFs, Office and text files) with your next message
  /exit   Quit the REPL (also /quit or Ctrl-D)
  /code REQUEST  Have the agent write code, in fenced blocks named after their files
""" + "\n".join(f"  /{command.name} {command.usage}  {command.description}" for command in COMMANDS.values())


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
    attachments: list[Attachment] = []
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
            attachments.clear()
            print("Agent reset.")
            continue
        if query == "/attach" or query.startswith("/attach "):
            try:
                # shlex reads quoted paths and the backslash escapes a terminal adds to a file dragged into it
                paths = shlex.split(query.removeprefix("/attach"))
            except ValueError as e:
                paths = []
                print(f"[error] {e}")
            for path in paths:
                try:
                    attachments.append(Attachment.from_path(path))
                except MediaError as e:
                    print(f"[error] {e}")
            if attachments:
                print("Attached to your next message: " + ", ".join(file.name for file in attachments))
            elif not paths:
                print("Usage: /attach PATH [PATH ...]")
            continue

        if invocation := parse_command(query):
            command, arguments = invocation
            try:
                reply = asyncio.run(command.run(CommandRun(agent, arguments, ResearchPrinter())))
                if command.reply_as_text:
                    print(f"\n{reply}")
            except KeyboardInterrupt:
                print("\n[interrupted]")
            except Exception as e:
                print(f"\n[error] {type(e).__name__}: {e}")
            continue

        # /code asks the agent itself, with a note on how to lay the code out
        code = query == "/code" or query.startswith("/code ")
        if code:
            query = query.removeprefix("/code").strip()
            if not query and not attachments:
                print("Usage: /code REQUEST")
                continue

        display.start_turn()
        try:
            # The display handler streams the labelled response to stdout
            agent.query(query, attachments = attachments, code = code)
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except MediaError as e:
            print(f"\n[error] {e}. Attach the files again once they're fixed.")
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}")
        finally:
            display.end_turn()
            attachments.clear()
