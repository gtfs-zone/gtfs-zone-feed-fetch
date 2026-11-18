"""GTFS zip members to typed rows, streaming each file and keeping only the
columns asked for."""

import csv
import io
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import BinaryIO

type ZipSource = bytes | BinaryIO

REQUIRED_FILES = ("agency", "routes", "trips", "stop_times", "stops")
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class MissingFiles(ValueError):
    """A GTFS zip without one of the files a timetable needs."""


@dataclass(frozen=True, slots=True)
class Agency:
    agency_id: str
    name: str
    url: str
    timezone: str
    phone: str
    lang: str = ""


@dataclass(frozen=True, slots=True)
class Stop:
    stop_id: str
    name: str
    lat: float | None
    lon: float | None
    code: str
    timezone: str
    parent_station: str
    wheelchair_boarding: int
    platform: str = ""
    zone_id: str = ""


@dataclass(frozen=True, slots=True)
class Calendar:
    service_id: str
    weekdays: tuple[bool, ...]
    start: date
    end: date


@dataclass(frozen=True, slots=True)
class FeedInfo:
    publisher_name: str
    publisher_url: str
    version: str
    start: date | None
    end: date | None
    lang: str = ""


def parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def parse_int(text: str) -> int | None:
    text = text.strip()
    return int(text) if text else None


def parse_float(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def open_zip(source: ZipSource) -> zipfile.ZipFile:
    """A ZipFile over zip bytes or a seekable binary file."""
    return zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source)


class Archive:
    """GTFS members by file name, tolerating one wrapping directory."""

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.archive = archive
        self.members: dict[str, str] = {}
        for name in sorted(archive.namelist(), key=lambda n: n.count("/")):
            if name.startswith("__MACOSX/") or not name.endswith(".txt"):
                continue
            self.members.setdefault(name.rsplit("/", 1)[-1][:-4], name)

    def has(self, table: str) -> bool:
        return table in self.members

    def missing(self) -> list[str]:
        """The files a timetable needs that the zip lacks."""
        missing = [table for table in REQUIRED_FILES if not self.has(table)]
        if not (self.has("calendar") or self.has("calendar_dates")):
            missing.append("calendar or calendar_dates")
        return missing

    def rows(self, table: str, columns: tuple[str, ...]) -> Iterator[dict[str, str]]:
        """Rows with only `columns`; a column missing from the file reads as ''."""
        for values in self.values(table, columns):
            yield dict(zip(columns, values, strict=True))

    def values(self, table: str, columns: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
        """Rows as tuples of `columns`; a column missing from the file reads as
        ''. Cheaper than `rows` for tables of millions of rows."""
        if table not in self.members:
            return
        with self.archive.open(self.members[table]) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
            header = [name.strip() for name in next(reader, [])]
            index = {name: i for i, name in enumerate(header)}
            picks = [index.get(column) for column in columns]
            for row in reader:
                if not row:
                    continue
                yield tuple(
                    row[i] if i is not None and i < len(row) else "" for i in picks
                )


def read_agencies(archive: Archive) -> dict[str, Agency]:
    columns = (
        "agency_id",
        "agency_name",
        "agency_url",
        "agency_timezone",
        "agency_phone",
        "agency_lang",
    )
    return {
        row["agency_id"]: Agency(
            agency_id=row["agency_id"],
            name=row["agency_name"],
            url=row["agency_url"],
            timezone=row["agency_timezone"],
            phone=row["agency_phone"],
            lang=row["agency_lang"].strip(),
        )
        for row in archive.rows("agency", columns)
    }


def read_stops(archive: Archive) -> dict[str, Stop]:
    columns = (
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "stop_code",
        "stop_timezone",
        "parent_station",
        "wheelchair_boarding",
        "platform_code",
        "zone_id",
    )
    return {
        row["stop_id"]: Stop(
            stop_id=row["stop_id"],
            name=row["stop_name"],
            lat=parse_float(row["stop_lat"]),
            lon=parse_float(row["stop_lon"]),
            code=row["stop_code"],
            timezone=row["stop_timezone"],
            parent_station=row["parent_station"],
            wheelchair_boarding=parse_int(row["wheelchair_boarding"]) or 0,
            platform=row["platform_code"],
            zone_id=row["zone_id"],
        )
        for row in archive.rows("stops", columns)
    }


def read_calendars(archive: Archive, service_ids: set[str]) -> dict[str, Calendar]:
    """Calendars of the given services."""
    calendars = {}
    for row in archive.rows(
        "calendar", ("service_id", "start_date", "end_date", *WEEKDAYS)
    ):
        if row["service_id"] not in service_ids:
            continue
        start, end = parse_date(row["start_date"]), parse_date(row["end_date"])
        if start is None or end is None:
            continue
        calendars[row["service_id"]] = Calendar(
            service_id=row["service_id"],
            weekdays=tuple(row[day].strip() == "1" for day in WEEKDAYS),
            start=start,
            end=end,
        )
    return calendars


def read_calendar_dates(
    archive: Archive, service_ids: set[str]
) -> dict[str, dict[date, bool]]:
    """service_id -> date -> True when added, False when removed, of the given
    services."""
    exceptions: dict[str, dict[date, bool]] = defaultdict(dict)
    for row in archive.rows("calendar_dates", ("service_id", "date", "exception_type")):
        if row["service_id"] not in service_ids:
            continue
        day = parse_date(row["date"])
        if day is not None:
            exceptions[row["service_id"]][day] = row["exception_type"].strip() == "1"
    return dict(exceptions)


def read_feed_info(archive: Archive) -> FeedInfo | None:
    columns = (
        "feed_publisher_name",
        "feed_publisher_url",
        "feed_version",
        "feed_start_date",
        "feed_end_date",
        "feed_lang",
    )
    for row in archive.rows("feed_info", columns):
        return FeedInfo(
            publisher_name=row["feed_publisher_name"],
            publisher_url=row["feed_publisher_url"],
            version=row["feed_version"],
            start=parse_date(row["feed_start_date"]),
            end=parse_date(row["feed_end_date"]),
            lang=row["feed_lang"].strip(),
        )
    return None
