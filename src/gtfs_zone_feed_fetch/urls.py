"""The comparison key ``gtfs/index.json`` is keyed by. No I/O."""

from urllib.parse import parse_qsl, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": "80", "https": "443"}


def is_absolute(url: str) -> bool:
    """Whether a URL names a host to talk to. The scheme's case is not its own."""
    return url.strip().lower().startswith(("http://", "https://"))


def normalize_url(url: str) -> str:
    """A comparison key for a download URL, or "" when there is nothing to compare.

    Lowercases the scheme and host, drops a default port, drops a trailing
    slash on an empty path, sorts query parameters and drops the fragment.
    http and https are *not* unified: a plain-http endpoint is a materially
    different thing to check, and some feeds exist only in that form. The key
    is never fetched, so it may lose information a request would need.
    """
    url = url.strip()
    if not is_absolute(url):
        return ""

    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        # A malformed host or port; there is nothing to compare.
        return ""
    scheme = parts.scheme.lower()
    netloc = (
        host
        if port is None or str(port) == DEFAULT_PORTS.get(scheme)
        else f"{host}:{port}"
    )

    path = parts.path.rstrip("/") if parts.path != "/" else ""
    query = "&".join(
        f"{k}={v}" for k, v in sorted(parse_qsl(parts.query, keep_blank_values=True))
    )
    return urlunsplit((scheme, netloc, path, query, ""))
