import hashlib

import pytest
from conftest import fixture_files, fixture_zip, make_zip

from gtfs_zone_feed_fetch.facts import scan
from gtfs_zone_feed_fetch.reader import MissingFiles

FEED_INFO = (
    "feed_publisher_name,feed_publisher_url,feed_version,feed_start_date,feed_end_date\n"
    "Test Pub,https://pub.example,v7,20260101,20261231\n"
)


@pytest.fixture
def scanned(tmp_path):
    def run(body: bytes) -> dict:
        path = tmp_path / "feed.zip"
        path.write_bytes(body)
        return scan(path)

    return run


def test_scan(scanned):
    body = fixture_zip("branching")
    facts = scanned(body)
    assert facts["bytes"] == len(body)
    assert facts["sha256"] == hashlib.sha256(body).hexdigest()
    assert facts["service"] == {"start": "2026-01-01", "end": "2026-12-31"}
    assert facts["agencies"] == [
        {
            "name": "Test Transit",
            "url": "https://example.org",
            "timezone": "America/New_York",
        }
    ]
    assert facts["counts"]["routes"] == 1
    assert facts["counts"]["stops"] > 0 and facts["counts"]["trips"] > 0
    assert facts["routeTypes"] == [3]
    assert facts["filtered"] is False
    assert "feedInfo" not in facts
    assert facts["languages"] == {"default": "en", "offered": ["en"], "readings": []}
    assert facts["location"]["bbox"] == [-73.6, 42.0, -73.0, 42.6]
    assert facts["location"]["stations"] == 7
    assert facts["placeTags"]["countries"] == ["United States"]
    assert facts["place"] == {
        "countryCode": "US",
        "country": "United States",
        "region": "",
    }


def test_scan_languages(scanned):
    facts = scanned(fixture_zip("languages"))
    assert facts["languages"] == {
        "default": "fr",
        "offered": ["fr", "en"],
        "readings": [],
    }


def test_scan_feed_info_and_calendar_dates(scanned):
    body = make_zip(fixture_files("calendar-dates-only") | {"feed_info.txt": FEED_INFO})
    facts = scanned(body)
    assert facts["feedInfo"] == {
        "publisher": "Test Pub",
        "publisherUrl": "https://pub.example",
        "version": "v7",
        "start": "2026-01-01",
        "end": "2026-12-31",
    }
    assert facts["service"]["start"] <= facts["service"]["end"]


def test_scan_in_a_folder(scanned):
    files = fixture_files("branching")
    facts = scanned(make_zip({f"gtfs/{name}": body for name, body in files.items()}))
    assert facts["location"]["stations"] == 7


def test_scan_missing_files(scanned):
    files = fixture_files("branching")
    del files["stop_times.txt"], files["calendar.txt"]
    with pytest.raises(MissingFiles, match="stop_times, calendar or calendar_dates"):
        scanned(make_zip(files))


def test_scan_tolerates_bad_route_types_and_language_codes(scanned):
    files = fixture_files("branching")
    header, *rows = files["routes.txt"].splitlines()
    column = header.split(",").index("route_type")
    bad = rows[0].split(",")
    bad[column] = "bus"
    files["routes.txt"] = "\n".join([header, ",".join(bad), *rows[1:]])
    files["feed_info.txt"] = (
        "feed_publisher_name,feed_publisher_url,feed_lang\nP,https://p.example,mul\n"
    )
    facts = scanned(make_zip(files))
    assert facts["routeTypes"] == []
    assert "languages" not in facts
    assert facts["counts"]["routes"] == 1


def test_stop_times_count_for_parent_stations(scanned):
    files = fixture_files("branching")
    header, *rows = files["stops.txt"].splitlines()
    files["stops.txt"] = "\n".join(
        [
            header + ",location_type,parent_station",
            *(row + ",0,P" for row in rows),
            "P,Parent,42.1,-73.1,,1,",
        ]
    )
    facts = scanned(make_zip(files))
    assert facts["location"]["stations"] == 1
    assert facts["location"]["center"] == [42.1, -73.1]


def _rows_reversed(body: str) -> str:
    header, *rows = body.splitlines()
    return "\n".join([header, *reversed(rows)]) + "\n"


def _columns_reversed(body: str) -> str:
    lines = [line.split(",")[::-1] for line in body.splitlines()]
    return "\n".join(",".join(line) for line in lines) + "\n"


def test_cleaned_hash_ignores_packaging(scanned):
    files = fixture_files("branching")
    base = scanned(make_zip(files))["cleanedHash"]
    assert len(base) == 64

    reordered = {name: _rows_reversed(body) for name, body in files.items()}
    assert scanned(make_zip(reordered))["cleanedHash"] == base

    swapped = dict(files, **{"stops.txt": _columns_reversed(files["stops.txt"])})
    assert scanned(make_zip(swapped))["cleanedHash"] == base

    crlf = {name: "﻿" + body.replace("\n", "\r\n") for name, body in files.items()}
    assert scanned(make_zip(crlf))["cleanedHash"] == base

    with_info = make_zip(files | {"feed_info.txt": FEED_INFO})
    assert scanned(with_info)["cleanedHash"] == base

    folder = make_zip({f"gtfs/{name}": body for name, body in files.items()})
    assert scanned(folder)["cleanedHash"] == base


def test_cleaned_hash_sees_every_table(scanned):
    files = fixture_files("branching")
    base = scanned(make_zip(files))["cleanedHash"]

    shapes = "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\ns1,42.0,-73.0,1\n"
    with_shapes = scanned(make_zip(files | {"shapes.txt": shapes}))["cleanedHash"]
    assert with_shapes != base
    moved = shapes.replace("42.0", "42.1")
    assert (
        scanned(make_zip(files | {"shapes.txt": moved}))["cleanedHash"] != with_shapes
    )

    header, first, *rest = files["stop_times.txt"].splitlines()
    doubled = "\n".join([header, first, first, *rest]) + "\n"
    changed = scanned(make_zip(files | {"stop_times.txt": doubled}))["cleanedHash"]
    assert changed != base

    empty_shapes = scanned(make_zip(files | {"shapes.txt": "shape_id\n"}))
    assert empty_shapes["cleanedHash"] == base
