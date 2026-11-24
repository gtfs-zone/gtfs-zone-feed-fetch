"""The schedule bucket's layout: ``gtfs/<sha256>.zip`` (or ``.body`` for a small
non-zip body), ``gtfs/<sha256>.facts.json`` and
``gtfs/<sha256>.fingerprint.parquet`` beside each zip, and
``gtfs/index.json`` mapping each normalized URL to its latest body. No I/O."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from gtfs_zone_feed_fetch.urls import normalize_url

PREFIX = "gtfs/"
INDEX_KEY = "gtfs/index.json"
ZIP_CONTENT_TYPE = "application/zip"

# Outcomes of one URL's last request.
OK = "ok"
NOT_MODIFIED = "not_modified"
TOO_LARGE = "too_large"
HTTP_ERROR = "http_error"
ERROR = "error"


@dataclass(frozen=True, slots=True)
class Stored:
    """One URL's entry in ``gtfs/index.json``."""

    # The URL as requested.
    url: str
    checked: str
    outcome: str
    status: int | None = None
    # The object holding the latest body; "" when none is stored.
    key: str = ""
    sha256: str = ""
    bytes: int | None = None
    # zip, html, json, xml, empty or unknown, from the body's first bytes.
    kind: str = ""
    content_type: str = ""
    # Header values as received, sent back as If-None-Match / If-Modified-Since.
    etag: str = ""
    last_modified: str = ""
    # When the body was last downloaded, and when its sha256 last changed.
    fetched: str = ""
    since: str = ""


INDEX_FIELDS = {
    "url": "url",
    "checked": "checked",
    "outcome": "outcome",
    "status": "status",
    "key": "key",
    "sha256": "sha256",
    "bytes": "bytes",
    "kind": "kind",
    "content_type": "contentType",
    "etag": "etag",
    "last_modified": "lastModified",
    "fetched": "fetched",
    "since": "since",
}


def to_json(entry: Stored) -> dict[str, Any]:
    return {name: getattr(entry, attr) for attr, name in INDEX_FIELDS.items()}


def from_json(data: dict[str, Any]) -> Stored:
    return Stored(
        **{attr: data[name] for attr, name in INDEX_FIELDS.items() if name in data}
    )


def parse_index(body: bytes) -> dict[str, Stored]:
    """The index by normalized URL."""
    urls = json.loads(body).get("urls", {})
    return {key: from_json(entry) for key, entry in urls.items()}


def lookup(index: dict[str, Stored], url: str) -> Stored | None:
    """The index entry for a download URL as any catalog spells it."""
    return index.get(normalize_url(url))


def stored_zip(entry: Stored | None) -> str:
    """The key of the entry's stored zip, else ""."""
    if entry is None or entry.kind != "zip" or not zip_sha256(entry.key):
        return ""
    return entry.key


def index_body(
    entries: dict[str, Stored], generated: datetime, max_bytes: int
) -> bytes:
    return json.dumps(
        {
            "generated": generated.isoformat(),
            "maxBytes": max_bytes,
            "urls": {key: to_json(entry) for key, entry in entries.items()},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def object_key(sha256: str, kind: str, size: int, body_max_bytes: int) -> str:
    """Where a body is stored, or "" for a non-zip body too large to keep."""
    if kind == "zip":
        return f"{PREFIX}{sha256}.zip"
    if size <= body_max_bytes:
        return f"{PREFIX}{sha256}.body"
    return ""


def facts_key(sha256: str) -> str:
    """Where the facts of the zip with this sha256 are kept."""
    return f"{PREFIX}{sha256}.facts.json"


def fingerprint_key(sha256: str) -> str:
    """Where the agency fingerprints of the zip with this sha256 are kept."""
    return f"{PREFIX}{sha256}.fingerprint.parquet"


def zip_sha256(key: str) -> str:
    """The sha256 of a ``gtfs/<sha256>.zip`` key, else ""."""
    name = key.removeprefix(PREFIX)
    if key.startswith(PREFIX) and name.endswith(".zip") and "/" not in name:
        return name.removesuffix(".zip")
    return ""
