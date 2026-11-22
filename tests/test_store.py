from datetime import UTC, datetime

from gtfs_zone_feed_fetch.store import (
    Stored,
    facts_key,
    index_body,
    lookup,
    object_key,
    parse_index,
    stored_zip,
    zip_sha256,
)


def test_index_round_trip():
    entry = Stored(
        url="https://example.org/gtfs.zip",
        checked="2026-11-19T09:00:00+00:00",
        outcome="ok",
        status=200,
        key="gtfs/abc.zip",
        sha256="abc",
        bytes=10,
        kind="zip",
        content_type="application/zip",
        etag='"v1"',
    )
    body = index_body({"example.org/gtfs.zip": entry}, datetime.now(UTC), 100)
    assert parse_index(body) == {"example.org/gtfs.zip": entry}
    assert b'"contentType":"application/zip"' in body


def test_keys():
    assert object_key("abc", "zip", 10**9, 100) == "gtfs/abc.zip"
    assert object_key("abc", "html", 100, 100) == "gtfs/abc.body"
    assert object_key("abc", "html", 101, 100) == ""
    assert facts_key("abc") == "gtfs/abc.facts.json"
    assert zip_sha256("gtfs/abc.zip") == "abc"
    assert zip_sha256("gtfs/abc.facts.json") == ""
    assert zip_sha256("gtfs/abc.body") == ""
    assert zip_sha256("gtfs/index.json") == ""


def test_lookup_normalizes_the_url_and_stored_zip_needs_a_zip():
    entry = Stored(
        url="https://example.org/gtfs.zip",
        checked="2026-11-19T09:00:00+00:00",
        outcome="not_modified",
        key="gtfs/abc.zip",
        sha256="abc",
        kind="zip",
    )
    index = {"https://example.org/gtfs.zip": entry}
    assert lookup(index, "HTTPS://Example.org:443/gtfs.zip") == entry
    assert lookup(index, "https://example.org/other.zip") is None
    assert stored_zip(entry) == "gtfs/abc.zip"
    assert stored_zip(None) == ""
    # Over the cap nothing is stored; an html body is not a zip.
    assert stored_zip(Stored(url="u", checked="c", outcome="too_large")) == ""
    html = Stored(url="u", checked="c", outcome="ok", key="gtfs/d.body", kind="html")
    assert stored_zip(html) == ""
