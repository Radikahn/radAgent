"""
Google Docs: writing new documents and changing existing ones

New documents and rewrites go through Drive, which converts Markdown into a formatted Doc (headings, lists, tables,
links); small edits go through the Docs API so the rest of the document, its comments and suggestions stay as they are.
Reading a Doc is google_drive_read, which exports it as Markdown
"""
from typing import Any

from radagent.tools.google import drive
from radagent.tools.google.client import DOCS_URL, UPLOAD_URL, GoogleError, call



def _upload_markdown(markdown: str, metadata: dict[str, Any] | None, file: str | None = None) -> dict[str, Any]:
    """
    Create a Doc from Markdown, or replace a Doc's whole contents with it

    Drive converts text/markdown into a formatted Doc; where it won't, the text goes in as it is
    """
    data = markdown.encode()
    if file is not None:
        query = {"uploadType": "media", "fields": drive.FILE_FIELDS, "supportsAllDrives": True}
        for mime in ("text/markdown", "text/plain"):
            try:
                return call("PATCH", f"{UPLOAD_URL}/files/{file}", query, data = data, content_type = mime)
            except GoogleError as e:
                if e.status != 400 or mime == "text/plain":
                    raise
    for mime in ("text/markdown", "text/plain"):
        try:
            return drive.upload({**(metadata or {}), "mimeType": drive.GOOGLE_DOC}, data, mime)
        except GoogleError as e:
            if e.status != 400 or mime == "text/plain":
                raise
    raise AssertionError("unreachable")


def create(title: str, markdown: str, folder: str | None) -> str:
    if not title.strip():
        raise ValueError("A new document needs a title")
    metadata: dict[str, Any] = {"name": title.strip()}
    if folder:
        metadata["parents"] = [drive.file_id(folder)]
    created = _upload_markdown(markdown, metadata)
    return f"Created the document {drive.describe(created)}"


def _end_index(document: str) -> int:
    """Where text appended to the document's body goes: just before its final newline"""
    data = call("GET", f"{DOCS_URL}/documents/{document}", {"fields": "body(content(endIndex))"})
    content = (data.get("body") or {}).get("content") or []
    return max(1, int(content[-1].get("endIndex", 2)) - 1) if content else 1


def _batch(document: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    return call("POST", f"{DOCS_URL}/documents/{document}:batchUpdate", body = {"requests": requests})


def edit(document: str, action: str, text: str | None, find: str | None, match_case: bool) -> str:
    target = drive.file_id(document)
    meta = drive.metadata(target)
    if meta.get("mimeType") != drive.GOOGLE_DOC:
        raise ValueError(f"{meta.get('name')} is a {drive.kind(meta.get('mimeType', ''))}, not a Google Doc")
    name = meta.get("name") or "the document"

    match action:
        case "append" | "prepend":
            if not text:
                raise ValueError(f"{action} needs text")
            index = _end_index(target) if action == "append" else 1
            # A paragraph of its own, rather than run on into the text beside it
            insert = ("\n" + text) if action == "append" else (text + "\n")
            _batch(target, [{"insertText": {"location": {"index": index}, "text": insert}}])
            return f"{'Added to the end of' if action == 'append' else 'Added to the start of'} {name}: {meta.get('webViewLink')}"
        case "replace":
            if not find:
                raise ValueError("replace needs the text to find")
            reply = _batch(target, [{"replaceAllText": {
                "containsText": {"text": find, "matchCase": match_case},
                "replaceText": text or "",
            }}])
            replies = reply.get("replies") or [{}]
            count = int((replies[0].get("replaceAllText") or {}).get("occurrencesChanged") or 0)
            if not count:
                return f"{find!r} isn't in {name}; nothing changed. Read it with google_drive_read to see its exact wording."
            return f"Replaced {count} occurrence(s) in {name}: {meta.get('webViewLink')}"
        case "rewrite":
            if text is None:
                raise ValueError("rewrite needs the document's new contents")
            updated = _upload_markdown(text, None, target)
            return (f"Rewrote {drive.describe(updated)}. The earlier version is in the document's version history "
                    f"(File > Version history).")
    raise ValueError(f"Unknown action {action!r}")
