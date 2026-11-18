"""Download one scheduled URL: a conditional GET with the last validators,
streamed to a temp file and hashed on the way."""

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from gtfs_zone_feed_fetch.sniff import sniff


@dataclass
class Fetched:
    status: int | None = None
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    path: Path | None = None
    sha256: str | None = None
    kind: str | None = None


def conditional_headers(etag: str | None, last_modified: str | None) -> dict[str, str]:
    """If-None-Match / If-Modified-Since for the validators given."""
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def fetch(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    workdir: Path,
    max_bytes: int,
) -> Fetched:
    """The response to a GET of `url` with `headers`. A 200 body is written to a
    temp file in `workdir` that the caller deletes."""
    try:
        with client.stream("GET", url, headers=headers) as response:
            out = Fetched(
                status=response.status_code,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
            if response.status_code != 200:
                return out
            digest = hashlib.sha256()
            size = 0
            head = b""
            with tempfile.NamedTemporaryFile(
                dir=workdir, suffix=".zip", delete=False
            ) as handle:
                out.path = Path(handle.name)
                for chunk in response.iter_bytes(1 << 20):
                    size += len(chunk)
                    if size > max_bytes:
                        out.error = f"larger than {max_bytes} bytes"
                        break
                    if len(head) < 512:
                        head += chunk[: 512 - len(head)]
                    digest.update(chunk)
                    handle.write(chunk)
            if out.error:
                out.path.unlink(missing_ok=True)
                out.path = None
                return out
            out.sha256 = digest.hexdigest()
            out.kind = sniff(head)
            return out
    except httpx.HTTPError as exc:
        return Fetched(error=f"{type(exc).__name__}: {exc}")
