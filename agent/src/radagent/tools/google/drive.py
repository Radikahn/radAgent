"""
Google Drive: finding files, reading them as text, and organizing them

Google's own formats are read through Drive's exports (Docs as Markdown, Sheets as CSV, Slides as text); PDFs and text
files are downloaded. Results are text for the model, each file with the ID the other google tools take
"""
import io
import json
import re
import uuid
from typing import Any

from radagent.tools.google.client import DRIVE_URL, UPLOAD_URL, GoogleError, call


FOLDER: str = "application/vnd.google-apps.folder"
GOOGLE_DOC: str = "application/vnd.google-apps.document"
GOOGLE_SHEET: str = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDES: str = "application/vnd.google-apps.presentation"
KINDS: dict[str, str] = {
    "folder": FOLDER,
    "doc": GOOGLE_DOC,
    "sheet": GOOGLE_SHEET,
    "slides": GOOGLE_SLIDES,
    "form": "application/vnd.google-apps.form",
    "pdf": "application/pdf",
}
# What a file is called in results
_KIND_NAMES: dict[str, str] = {mime: kind for kind, mime in KINDS.items()}

FILE_FIELDS: str = ("id,name,mimeType,modifiedTime,size,webViewLink,ownedByMe,owners(displayName,emailAddress),"
                    "parents,trashed,starred,shared,description")
# Larger downloads are refused rather than read; Drive's own exports stop at 10 MB
MAX_DOWNLOAD_BYTES: int = 20 * 1024 * 1024
PAGE_LIMIT: int = 100

# The ID in the links people paste: /d/<id>/, /folders/<id>, ?id=<id>
_LINK_ID = re.compile(r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_-]{10,})")
_BARE_ID = re.compile(r"[A-Za-z0-9_-]{10,}")
_TEXT_TYPES: tuple[str, ...] = ("application/json", "application/xml", "application/javascript", "application/x-yaml",
                                "application/sql", "application/x-sh", "image/svg+xml")



def file_id(value: str) -> str:
    """The file ID in a Drive or Docs link, or `value` itself when it's a bare ID"""
    value = value.strip()
    if match := _LINK_ID.search(value):
        return match.group(1)
    if value == "root" or _BARE_ID.fullmatch(value):
        return value
    raise ValueError(f"{value!r} isn't a Google Drive file ID or link")


def _quote(text: str) -> str:
    """`text` as a string literal in a Drive query"""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def kind(mime: str) -> str:
    return _KIND_NAMES.get(mime) or mime.removeprefix("application/vnd.google-apps.")


def describe(file: dict[str, Any]) -> str:
    """One file as a line of a result"""
    parts = [f"{file.get('name') or '(untitled)'} [{kind(file.get('mimeType', ''))}]", f"id {file['id']}"]
    if modified := file.get("modifiedTime"):
        parts.append(f"modified {modified[:16].replace('T', ' ')} UTC")
    if file.get("ownedByMe"):
        parts.append("owned by the user")
    elif owners := file.get("owners"):
        parts.append("owner " + ", ".join(owner.get("emailAddress") or owner.get("displayName", "?") for owner in owners))
    if size := file.get("size"):
        parts.append(f"{int(size):,} bytes")
    if file.get("trashed"):
        parts.append("in the trash")
    if link := file.get("webViewLink"):
        parts.append(link)
    return " · ".join(parts)


def metadata(file: str) -> dict[str, Any]:
    return call("GET", f"{DRIVE_URL}/files/{file_id(file)}", {"fields": FILE_FIELDS, "supportsAllDrives": True})



# ---- Finding ----

def search(
    text: str | None,
    name: str | None,
    kind_filter: str | None,
    folder: str | None,
    modified_after: str | None,
    query: str | None,
    limit: int,
    page_token: str | None,
    trashed: bool,
) -> str:
    clauses: list[str] = []
    if query:
        clauses.append(f"({query})")
    if text:
        clauses.append(f"fullText contains {_quote(text)}")
    if name:
        clauses.append(f"name contains {_quote(name)}")
    if kind_filter:
        clauses.append(f"mimeType = {_quote(KINDS.get(kind_filter, kind_filter))}")
    if folder:
        clauses.append(f"{_quote(file_id(folder))} in parents")
    if modified_after:
        stamp = modified_after if "T" in modified_after else modified_after + "T00:00:00"
        clauses.append(f"modifiedTime > {_quote(stamp)}")
    if not trashed and "trashed" not in (query or ""):
        clauses.append("trashed = false")

    params: dict[str, Any] = {
        "q": " and ".join(clauses),
        "pageSize": limit,
        "pageToken": page_token,
        "fields": f"nextPageToken,files({FILE_FIELDS})",
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
        "corpora": "allDrives",
    }
    # Drive can't sort a full-text search; it ranks those by relevance instead
    if not text and "fullText" not in (query or ""):
        params["orderBy"] = "folder,modifiedTime desc" if folder else "modifiedTime desc"
    data = call("GET", f"{DRIVE_URL}/files", params)
    files = data.get("files") or []
    if not files:
        return "No files found."
    lines = [f"{len(files)} file(s):", *(f"- {describe(file)}" for file in files)]
    if token := data.get("nextPageToken"):
        lines.append(f"More results: call again with page_token={token!r}.")
    return "\n".join(lines)



# ---- Reading ----

def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = [f"[page {n}]\n{(page.extract_text() or '').strip()}" for n, page in enumerate(reader.pages, start = 1)]
    return "\n\n".join(pages)


def _is_text(mime: str) -> bool:
    return mime.startswith("text/") or mime in _TEXT_TYPES or mime.endswith(("+json", "+xml"))


def _export(file: str, mime: str) -> str:
    return call("GET", f"{DRIVE_URL}/files/{file}/export", {"mimeType": mime}, raw = True).decode("utf-8", "replace")


def content(meta: dict[str, Any]) -> str:
    """
    A file's contents as text

    Raises:
        ValueError: The file can't be read as text
    """
    mime, file = meta.get("mimeType", ""), meta["id"]
    if mime == GOOGLE_DOC:
        try:
            return _export(file, "text/markdown")
        except GoogleError as e:
            if e.status not in (400, 403):
                raise
            return _export(file, "text/plain")
    if mime == GOOGLE_SHEET:
        return "(Drive exports only a spreadsheet's first sheet)\n" + _export(file, "text/csv")
    if mime == GOOGLE_SLIDES:
        return _export(file, "text/plain")
    if mime == FOLDER:
        return search(None, None, None, file, None, None, PAGE_LIMIT, None, False)
    if mime.startswith("application/vnd.google-apps."):
        raise ValueError(f"Drive can't export a {kind(mime)} as text; open it at {meta.get('webViewLink')}")
    if mime != "application/pdf" and not _is_text(mime):
        raise ValueError(f"This is a {mime} file, which can't be read as text; open it at {meta.get('webViewLink')}")
    if int(meta.get("size") or 0) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"It's {int(meta['size']):,} bytes, too large to read here; open it at {meta.get('webViewLink')}")
    data = call("GET", f"{DRIVE_URL}/files/{file}", {"alt": "media", "supportsAllDrives": True}, raw = True)
    if mime == "application/pdf":
        return _pdf_text(data)
    return data.decode("utf-8", "replace")


def read(file: str, offset: int, max_chars: int) -> str:
    meta = metadata(file)
    text = content(meta)
    window = text[offset:offset + max_chars]
    lines = [describe(meta)]
    if description := meta.get("description"):
        lines.append(f"Description: {description}")
    rest = len(text) - offset - len(window)
    lines += ["", window if window else "(nothing here at this offset)" if text else "(empty)"]
    if rest > 0:
        lines += ["", f"[{rest:,} more characters; call again with offset={offset + len(window)} to read on]"]
    return "\n".join(lines)



# ---- Organizing ----

def upload(metadata_: dict[str, Any], data: bytes, mime: str, file: str | None = None) -> dict[str, Any]:
    """Create a file with contents (or replace an existing one's), in one multipart request"""
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
        json.dumps(metadata_).encode(),
        f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--".encode(),
    ])
    url = f"{UPLOAD_URL}/files" + (f"/{file}" if file else "")
    return call("PATCH" if file else "POST", url, {"uploadType": "multipart", "fields": FILE_FIELDS,
                                                    "supportsAllDrives": True},
                data = body, content_type = f"multipart/related; boundary={boundary}")


def manage(
    action: str,
    file: str | None,
    name: str | None,
    folder: str | None,
    text: str | None,
    mime_type: str | None,
) -> str:
    files = f"{DRIVE_URL}/files"
    base: dict[str, Any] = {"fields": FILE_FIELDS, "supportsAllDrives": True}
    parents = [file_id(folder)] if folder else None

    match action:
        case "create_folder":
            if not name:
                raise ValueError("create_folder needs a name")
            created = call("POST", files, base, {"name": name, "mimeType": FOLDER, **({"parents": parents} if parents else {})})
            return f"Created the folder {describe(created)}"
        case "create_file":
            if not name:
                raise ValueError("create_file needs a name")
            meta: dict[str, Any] = {"name": name, **({"parents": parents} if parents else {})}
            created = upload(meta, (text or "").encode(), mime_type or "text/plain")
            return f"Created {describe(created)}"

    if not file:
        raise ValueError(f"{action} needs a file")
    target = file_id(file)
    match action:
        case "rename":
            if not name:
                raise ValueError("rename needs a name")
            return f"Renamed: {describe(call('PATCH', f'{files}/{target}', base, {'name': name}))}"
        case "move":
            if not parents:
                raise ValueError("move needs a folder (\"root\" for My Drive)")
            current = call("GET", f"{files}/{target}", {"fields": "parents", "supportsAllDrives": True})
            moved = call("PATCH", f"{files}/{target}",
                         {**base, "addParents": parents[0], "removeParents": ",".join(current.get("parents") or [])}, {})
            return f"Moved: {describe(moved)}"
        case "copy":
            meta = {**({"name": name} if name else {}), **({"parents": parents} if parents else {})}
            return f"Copied to {describe(call('POST', f'{files}/{target}/copy', base, meta))}"
        case "update_text":
            if text is None:
                raise ValueError("update_text needs text")
            current = metadata(target)
            if current.get("mimeType", "").startswith("application/vnd.google-apps."):
                raise ValueError("That's a Google file; edit Docs with google_docs_edit")
            updated = upload({}, text.encode(), mime_type or current.get("mimeType") or "text/plain", target)
            return f"Replaced the contents of {describe(updated)}"
        case "trash" | "untrash":
            changed = call("PATCH", f"{files}/{target}", base, {"trashed": action == "trash"})
            return f"{'Moved to the trash' if action == 'trash' else 'Restored from the trash'}: {describe(changed)}"
    raise ValueError(f"Unknown action {action!r}")
