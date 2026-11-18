from datetime import UTC, datetime

from gtfs_zone_feed_fetch.store import (
    Stored,
    facts_key,
    index_body,
    object_key,
    parse_index,
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
