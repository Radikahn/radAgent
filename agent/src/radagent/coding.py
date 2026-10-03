"""
/code: the user wants code written. The message goes to the agent like any other, with a note ahead of it asking for
working code laid out the way the app draws it: each fenced block becomes a box with its file's name, syntax
highlighting and a copy button (client/src/chat/CodeBlock.tsx). server/history.py hides the note again
"""

CODE_NOTE: str = (
    "<code_request>The user started this message with /code: they want you to write code. Write it in your reply, "
    "complete and ready to run rather than an outline or pseudo-code, and don't leave parts out with \"...\"; when "
    "you change code they gave you, show each changed part whole and say where it goes. Put each file in its own "
    "fenced code block, and open the fence with the language followed by the file's path when the code belongs in "
    "a file, e.g. ```python src/app.py. Commands go in their own ```bash block, without a prompt or their output. "
    "Keep the prose short: a line or two on the approach before the code, and how to run it after. Make sensible "
    "choices instead of asking, and say what you assumed. Before you write anything you may run the code once with "
    "the shell in a temporary folder to catch mistakes, using only what's already installed; then write the reply in "
    "one go, without describing the run. Leave other files alone unless asked.</code_request>"
)


def is_code_note(text: str) -> bool:
    return text.startswith("<code_request>")
