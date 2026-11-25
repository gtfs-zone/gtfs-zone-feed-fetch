"""Agency fingerprints: the cells of a global grid an agency's trips stop in,
and the (cell, next cell) edges between consecutive stops. Positions only, no
times, so copies of a feed match whatever their service dates.

The grid has rows of `CELL_METRES` in latitude and, within a row, columns of
`CELL_METRES` at the row's centre, so every feed snaps to the same cells. A
stop is placed at its parent station when it has one. A cell is an int,
row << 32 | column; an edge is an int, cell << 64 | next cell.

`to_parquet` writes a feed's fingerprint as one row per agency: agency_id,
name, its sorted cells, and its edges sorted as two aligned columns of start
and end cells; the file's metadata holds `FINGERPRINT_VERSION`, the cell size
and the reappearances."""

import io
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise

import pyarrow as pa
import pyarrow.parquet as pq

from gtfs_zone_feed_fetch.reader import Agency, Stop

# Bumped when the same zip would give a different fingerprint file.
FINGERPRINT_VERSION = 1
CELL_METRES = 150
METRES_PER_DEGREE = 111_320.0
ROW_DEGREES = CELL_METRES / METRES_PER_DEGREE
CELL_MASK = (1 << 64) - 1
# Cell offsets of the 3 x 3 block around a cell.
NEIGHBOURS = tuple((row << 32) + column for row in (-1, 0, 1) for column in (-1, 0, 1))


@dataclass(frozen=True, slots=True)
class AgencyFingerprint:
    agency_id: str
    name: str
    cells: frozenset[int]
    edges: frozenset[int]


@dataclass(frozen=True, slots=True)
class FeedFingerprint:
    agencies: tuple[AgencyFingerprint, ...]
    # Times a trip's stop_times rows started again after they had ended.
    reappearances: int


def cell(lat: float, lon: float) -> int | None:
    """The grid cell of a position, None outside the valid range or at 0, 0."""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or lat == lon == 0:
        return None
    row = math.floor((lat + 90.0) / ROW_DEGREES)
    centre = (row + 0.5) * ROW_DEGREES - 90.0
    column_degrees = CELL_METRES / (METRES_PER_DEGREE * math.cos(math.radians(centre)))
    return row << 32 | math.floor((lon + 180.0) / column_degrees)


def containment(small: AgencyFingerprint, big: AgencyFingerprint) -> float:
    """Share of `small`'s edges whose two ends are each within one cell of the
    ends of one of `big`'s edges; 0 when `small` has no edges."""
    if not small.edges:
        return 0.0
    edges = big.edges
    hits = 0
    for edge in small.edges:
        if edge in edges:
            hits += 1
            continue
        start, end = edge >> 64, edge & CELL_MASK
        if any(
            ((start + a) << 64 | (end + b)) in edges
            for a in NEIGHBOURS
            for b in NEIGHBOURS
        ):
            hits += 1
    return hits / len(small.edges)


def stop_cells(stops: dict[str, Stop]) -> dict[str, int]:
    """Cell of each located stop, at its parent station when it has one."""
    cells = {}
    for stop_id, stop in stops.items():
        place = stops.get(stop.parent_station, stop) if stop.parent_station else stop
        if place.lat is None or place.lon is None:
            continue
        if (found := cell(place.lat, place.lon)) is not None:
            cells[stop_id] = found
    return cells


class Fingerprinter:
    """Collects routes, trips and one pass over stop_times into a
    `FeedFingerprint`. A trip's rows are put in stop_sequence order; its sorted
    (sequence, cell) pattern is kept, interned, so a trip seen again after its
    rows ended is merged with them. Cells and edges come from the patterns
    still in use at `finish`."""

    def __init__(self, stops: dict[str, Stop], agencies: dict[str, Agency]) -> None:
        self.cells = stop_cells(stops)
        self.agency_ids = list(agencies)
        self.names = {agency_id: agency.name for agency_id, agency in agencies.items()}
        self.only = self.agency_ids[0] if len(self.agency_ids) == 1 else None
        self.indexes = {agency_id: i for i, agency_id in enumerate(self.agency_ids)}
        self.route_agency: dict[str, int] = {}
        # trip_id to its agency index before its rows are read, then to the
        # [pattern, trips using it] entry of `patterns`.
        self.trips: dict[str, int | list] = {}
        self.patterns: dict[tuple[int, ...], list] = {}
        self.reappearances = 0

    def _agency(self, agency_id: str) -> int:
        """Index of an agency; an empty id is the feed's only agency, an id
        missing from agency.txt is an agency of its own."""
        if not agency_id and self.only is not None:
            agency_id = self.only
        index = self.indexes.get(agency_id)
        if index is None:
            index = self.indexes[agency_id] = len(self.agency_ids)
            self.agency_ids.append(agency_id)
        return index

    def add_route(self, route_id: str, agency_id: str) -> None:
        self.route_agency[route_id] = self._agency(agency_id)

    def add_trip(self, trip_id: str, route_id: str) -> None:
        agency = self.route_agency.get(route_id)
        if agency is not None:
            self.trips[trip_id] = agency

    def trace(self, rows: Iterable[tuple[str, str, str]]) -> Iterator[str]:
        """Reads (trip_id, stop_id, stop_sequence) rows, yielding each stop_id."""
        trip = None
        held: list[tuple[str, str]] = []
        for trip_id, stop_id, sequence in rows:
            if trip_id != trip:
                if held:
                    self._end(trip, held)
                trip = trip_id
                held = []
            held.append((sequence, stop_id))
            yield stop_id
        if held:
            self._end(trip, held)

    def _end(self, trip_id: str, held: list[tuple[str, str]]) -> None:
        """Files the rows of one run of a trip in the file."""
        state = self.trips.get(trip_id)
        if state is None:
            return
        cells = self.cells
        try:
            located = [
                (int(sequence), cells[stop_id])
                for sequence, stop_id in held
                if stop_id in cells
            ]
        except ValueError:
            # stop_sequence is not an integer: file order.
            located = [
                (i, cells[stop_id])
                for i, (_, stop_id) in enumerate(held)
                if stop_id in cells
            ]
        if isinstance(state, list):
            self.reappearances += 1
            pattern = state[0]
            state[1] -= 1
            if not state[1]:
                del self.patterns[pattern]
            agency = pattern[0]
            located.extend(zip(pattern[1::2], pattern[2::2], strict=True))
        else:
            agency = state
        located.sort()
        pattern = (agency, *(value for pair in located for value in pair))
        entry = self.patterns.get(pattern)
        if entry is None:
            entry = self.patterns[pattern] = [pattern, 0]
        entry[1] += 1
        self.trips[trip_id] = entry

    def finish(self) -> FeedFingerprint:
        cells: list[set[int]] = [set() for _ in self.agency_ids]
        edges: list[set[int]] = [set() for _ in self.agency_ids]
        for pattern in self.patterns:
            agency = pattern[0]
            sequence = pattern[2::2]
            cells[agency].update(sequence)
            add = edges[agency].add
            for start, end in pairwise(sequence):
                if start != end:
                    add(start << 64 | end)
        return FeedFingerprint(
            agencies=tuple(
                AgencyFingerprint(
                    agency_id=agency_id,
                    name=self.names.get(agency_id, ""),
                    cells=frozenset(cells[i]),
                    edges=frozenset(edges[i]),
                )
                for i, agency_id in enumerate(self.agency_ids)
            ),
            reappearances=self.reappearances,
        )


SCHEMA = pa.schema(
    [
        ("agency_id", pa.string()),
        ("name", pa.string()),
        ("cells", pa.list_(pa.int64())),
        ("edge_from", pa.list_(pa.int64())),
        ("edge_to", pa.list_(pa.int64())),
    ]
)


def to_parquet(fingerprint: FeedFingerprint) -> bytes:
    """The fingerprint as a zstd parquet file."""
    agencies = fingerprint.agencies
    edges = [sorted(agency.edges) for agency in agencies]
    table = pa.table(
        {
            "agency_id": [agency.agency_id for agency in agencies],
            "name": [agency.name for agency in agencies],
            "cells": [sorted(agency.cells) for agency in agencies],
            "edge_from": [[edge >> 64 for edge in sorted_] for sorted_ in edges],
            "edge_to": [[edge & CELL_MASK for edge in sorted_] for sorted_ in edges],
        },
        schema=SCHEMA.with_metadata(
            {
                "version": str(FINGERPRINT_VERSION),
                "cell_metres": str(CELL_METRES),
                "reappearances": str(fingerprint.reappearances),
            }
        ),
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="zstd")
    return buffer.getvalue()


def from_parquet(body: bytes) -> FeedFingerprint:
    """A fingerprint written by `to_parquet` of this `FINGERPRINT_VERSION`;
    ValueError for another version."""
    table = pq.read_table(io.BytesIO(body))
    metadata = table.schema.metadata or {}
    version = metadata.get(b"version", b"").decode()
    if version != str(FINGERPRINT_VERSION):
        raise ValueError(f"fingerprint version {version!r}, not {FINGERPRINT_VERSION}")
    return FeedFingerprint(
        agencies=tuple(
            AgencyFingerprint(
                agency_id=row["agency_id"],
                name=row["name"],
                cells=frozenset(row["cells"]),
                edges=frozenset(
                    start << 64 | end
                    for start, end in zip(row["edge_from"], row["edge_to"], strict=True)
                ),
            )
            for row in table.to_pylist()
        ),
        reappearances=int(metadata[b"reappearances"]),
    )
