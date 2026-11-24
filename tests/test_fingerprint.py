import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import fixture_files, make_zip

from gtfs_zone_feed_fetch.facts import scan, scan_archive, scan_fingerprinted
from gtfs_zone_feed_fetch.fingerprint import (
    AgencyFingerprint,
    FeedFingerprint,
    cell,
    containment,
    from_parquet,
    to_parquet,
)
from gtfs_zone_feed_fetch.reader import Archive, open_zip


def fingerprint(files: dict[str, str]) -> FeedFingerprint:
    with open_zip(make_zip(files)) as raw:
        return scan_archive(Archive(raw))[2]


def agency(feed: FeedFingerprint, name: str) -> AgencyFingerprint:
    return next(a for a in feed.agencies if a.name == name)


def moved(files: dict[str, str], dlat: float, dlon: float) -> dict[str, str]:
    """`files` with every stop moved by dlat, dlon degrees."""
    lines = files["stops.txt"].splitlines()
    rows = [lines[0]]
    for line in lines[1:]:
        values = line.split(",")
        values[2] = str(float(values[2]) + dlat)
        values[3] = str(float(values[3]) + dlon)
        rows.append(",".join(values))
    return {**files, "stops.txt": "\n".join(rows) + "\n"}


def edge(*stop: tuple[float, float]) -> int:
    start, end = (cell(lat, lon) for lat, lon in stop)
    assert start is not None and end is not None
    return start << 64 | end


S1, S2, S3, S4, S5 = (
    (42.35, -71.06),
    (42.35, -71.052),
    (42.35, -71.044),
    (42.35, -71.036),
    (42.358, -71.052),
)
NORTH, SOUTH = (42.366, -71.062), (42.352, -71.055)


def test_cells_and_edges():
    feed = fingerprint(fixture_files("fingerprint-city"))
    bus = agency(feed, "City Bus")
    assert bus.agency_id == "CB"
    assert bus.cells == {cell(*stop) for stop in (S1, S2, S3, S4, S5)}
    # "back" is listed in reverse stop_sequence order and still runs S4 to S1.
    assert bus.edges == {
        edge(S1, S2),
        edge(S2, S3),
        edge(S3, S4),
        edge(S4, S3),
        edge(S3, S2),
        edge(S2, S1),
        edge(S2, S5),
    }
    # Platforms are placed at their parent stations.
    rail = agency(feed, "Metro Rail")
    assert rail.cells == {cell(*NORTH), cell(*SOUTH)}
    assert rail.edges == {edge(NORTH, SOUTH)}


def test_split_trip_is_merged():
    files = fixture_files("fingerprint-city")
    split = fingerprint(files)
    assert split.reappearances == 1
    lines = files["stop_times.txt"].splitlines()
    grouped = [lines[0], *sorted(lines[1:], key=lambda line: line.split(",")[0])]
    together = fingerprint({**files, "stop_times.txt": "\n".join(grouped) + "\n"})
    assert together.reappearances == 0
    assert split.agencies == together.agencies


def test_stops_shifted_under_one_cell_match():
    files = fixture_files("fingerprint-city")
    bus = agency(fingerprint(files), "City Bus")
    shifted = agency(fingerprint(moved(files, 0.0003, 0.0003)), "City Bus")
    assert shifted.cells != bus.cells
    assert containment(shifted, bus) == 1.0
    assert containment(bus, shifted) == 1.0


def test_same_name_on_other_streets_does_not_match():
    files = fixture_files("fingerprint-city")
    bus = agency(fingerprint(files), "City Bus")
    elsewhere = agency(fingerprint(moved(files, 0.004, 0)), "City Bus")
    assert containment(elsewhere, bus) == 0.0


def test_part_of_a_feed():
    feed = fingerprint(fixture_files("fingerprint-city"))
    bus, rail = agency(feed, "City Bus"), agency(feed, "Metro Rail")
    main_street = AgencyFingerprint(
        "", "", frozenset(), frozenset({edge(S1, S2), edge(S2, S3), edge(NORTH, S5)})
    )
    assert containment(main_street, bus) == 2 / 3
    assert containment(rail, bus) == 0.0
    assert containment(AgencyFingerprint("", "", frozenset(), frozenset()), bus) == 0


def test_feed_without_agency_id():
    feed = fingerprint(fixture_files("fingerprint-no-agency-id"))
    (shuttle,) = feed.agencies
    assert (shuttle.agency_id, shuttle.name) == ("", "Town Shuttle")
    assert shuttle.edges == {edge((42.35, -71.06), (42.35, -71.052))}


def test_cell_outside_range():
    assert cell(0, 0) is None
    assert cell(91, 10) is None
    assert cell(10, -181) is None
    assert cell(-90, -180) == 0


def test_parquet_round_trip():
    feed = fingerprint(fixture_files("fingerprint-city"))
    body = to_parquet(feed)
    assert from_parquet(body) == feed
    table = pq.read_table(pa.BufferReader(body))
    assert table.schema.metadata[b"cell_metres"] == b"150"
    bus = table.to_pylist()[0]
    assert bus["cells"] == sorted(bus["cells"])
    assert list(zip(bus["edge_from"], bus["edge_to"], strict=True)) == sorted(
        zip(bus["edge_from"], bus["edge_to"], strict=True)
    )


def test_parquet_of_another_version_is_refused():
    table = pq.read_table(
        pa.BufferReader(
            to_parquet(fingerprint(fixture_files("fingerprint-no-agency-id")))
        )
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table.replace_schema_metadata({"version": "0"}), sink)
    with pytest.raises(ValueError, match="version"):
        from_parquet(sink.getvalue().to_pybytes())


def test_scan_fingerprinted(tmp_path):
    path = tmp_path / "feed.zip"
    path.write_bytes(make_zip(fixture_files("fingerprint-city")))
    facts, feed = scan_fingerprinted(path)
    assert facts == scan(path)
    assert feed == fingerprint(fixture_files("fingerprint-city"))
