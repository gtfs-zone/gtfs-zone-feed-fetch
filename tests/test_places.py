from collections import Counter

from conftest import fixture_files, make_zip

from gtfs_zone_feed_fetch.places import (
    Located,
    Place,
    feed_location,
    feed_place,
    locate,
    place_label,
    place_tags,
    station_weights,
)
from gtfs_zone_feed_fetch.reader import Archive, open_zip, read_stops

OREGON = Place("Oregon", "United States", "US", 45.5, -122.7)


def stations_of(body: bytes) -> list[Located]:
    with open_zip(body) as raw:
        archive = Archive(raw)
        counts = Counter(s for (s,) in archive.values("stop_times", ("stop_id",)))
        return locate(station_weights(read_stops(archive), counts))


def branching(stops: list[tuple[float, float]] | None = None) -> bytes:
    files = fixture_files("branching")
    if stops is not None:
        rows = files["stops.txt"].splitlines()
        files["stops.txt"] = "\n".join(
            [rows[0]]
            + [
                ",".join([*row.split(",")[:2], str(lat), str(lon), ""])
                for row, (lat, lon) in zip(rows[1:], stops, strict=True)
            ]
        )
    return make_zip(files)


PORTLAND = [(45.5 + i / 100, -122.65 - i / 100) for i in range(7)]


def test_feed_place_is_the_region_holding_the_stop_times():
    place = feed_place(stations_of(branching(PORTLAND)))
    assert (place.region, place.country_code) == ("Oregon", "US")


def test_a_feed_across_regions_is_named_by_its_country():
    place = feed_place(stations_of(branching()))
    assert (place.region, place.country) == ("", "United States")


def test_place_label():
    assert place_label(OREGON, "TriMet") == "Oregon"
    assert place_label(OREGON, "Oregon Coast Transit") == ""
    national = Place("", "United States", "US", 39.0, -98.0)
    assert place_label(national, "Amtrak") == "United States"
    assert place_label(None, "Amtrak") == ""
    assert place_label(OREGON, "TriMet", "Portland") == "Portland, Oregon"
    assert place_label(None, "TriMet", "Portland") == "Portland"
    # Parts the title already names are left out.
    assert place_label(OREGON, "Portland Streetcar", "Portland") == "Oregon"
    assert place_label(OREGON, "Oregon Coast Transit", "Newport") == "Newport"
    assert place_label(OREGON, "TriMet", "Oregon") == "Oregon"


def test_feed_location_and_place_tags():
    stations = stations_of(branching(PORTLAND))
    location = feed_location(stations)
    assert location["bbox"] == [-122.71, 45.5, -122.65, 45.56]
    assert location["stations"] == 7
    lat, lon = location["center"]
    assert 45.5 <= lat <= 45.56 and -122.71 <= lon <= -122.65
    tags = place_tags(stations)
    assert tags == {"countries": ["United States"], "regions": ["Oregon"]}


def test_place_tags_rank_regions_by_stop_times():
    stations = stations_of(branching())
    tags = place_tags(stations)
    assert tags["countries"] == ["United States"]
    weights = {s.region: 0 for s in stations}
    for s in stations:
        weights[s.region] += s.weight
    assert len(tags["regions"]) > 1
    assert [weights[r] for r in tags["regions"]] == sorted(
        (weights[r] for r in tags["regions"]), reverse=True
    )


def test_unlocated_and_unknown_stops_are_skipped():
    with open_zip(branching()) as raw:
        stops = read_stops(Archive(raw))
    weights = station_weights(stops, {"A": 2, "missing": 5})
    assert weights == {(stops["A"].lat, stops["A"].lon): 2}


def test_nothing_located():
    assert locate({}) == []
    assert feed_location([]) is None
    assert feed_place([]) is None
    assert place_tags([]) == {"countries": [], "regions": []}
