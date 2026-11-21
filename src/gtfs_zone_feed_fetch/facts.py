"""What a GTFS zip contains: feed_info, service range, agencies, counts,
languages and where it runs.

`feed_facts` turns a `Summary` into the facts document. A caller that has
already parsed the feed fills the summary from it; `scan` fills it from the
whole zip in one streaming pass, keeping a count per stop and nothing per trip,
so the largest feeds fit in a few hundred MB."""

import hashlib
import io
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from gtfs_zone_feed_fetch.languages import FeedLanguages, feed_languages
from gtfs_zone_feed_fetch.localities import Localities
from gtfs_zone_feed_fetch.places import (
    Located,
    feed_location,
    feed_place,
    locate,
    place_tags,
    station_weights,
)
from gtfs_zone_feed_fetch.reader import (
    Agency,
    Archive,
    FeedInfo,
    MissingFiles,
    ZipSource,
    open_zip,
    parse_int,
    read_agencies,
    read_calendar_dates,
    read_calendars,
    read_feed_info,
    read_stops,
)
from gtfs_zone_feed_fetch.service import service_range

# Bumped when `scan` or `feed_facts` would give a different document for the
# same zip, so stored facts are computed again.
FACTS_VERSION = 2


@dataclass(frozen=True, slots=True)
class Summary:
    agencies: tuple[Agency, ...]
    feed_info: FeedInfo | None
    routes: int
    route_types: frozenset[int]
    stops: int
    trips: int
    start: date | None
    end: date | None
    # None when feed_lang is mul with no other language to go by.
    languages: FeedLanguages | None


def zip_digest(source: ZipSource) -> tuple[int, str]:
    """Size and sha256 of zip bytes or a seekable binary file."""
    if isinstance(source, bytes):
        return len(source), hashlib.sha256(source).hexdigest()
    source.seek(0)
    digest = hashlib.file_digest(source, "sha256").hexdigest()
    return source.seek(0, io.SEEK_END), digest


def feed_facts(
    size: int,
    sha256: str,
    summary: Summary,
    filtered: bool,
    stations: list[Located],
) -> dict[str, Any]:
    """Size, hash, feed_info, service range, agencies, counts, languages and
    location, with `stations` the feed's located stations. `filtered` marks
    counts taken after a route filter."""
    start, end = summary.start, summary.end
    facts: dict[str, Any] = {
        "bytes": size,
        "sha256": sha256,
        "service": {
            "start": start and start.isoformat(),
            "end": end and end.isoformat(),
        },
        "agencies": [
            {"name": agency.name, "url": agency.url, "timezone": agency.timezone}
            for agency in summary.agencies
        ],
        "counts": {
            "routes": summary.routes,
            "stops": summary.stops,
            "trips": summary.trips,
        },
        "routeTypes": sorted(summary.route_types),
        "filtered": filtered,
    }
    if languages := summary.languages:
        facts["languages"] = {
            "default": languages.default,
            "offered": list(languages.offered),
            "readings": list(languages.readings),
        }
    if info := summary.feed_info:
        facts["feedInfo"] = {
            "publisher": info.publisher_name,
            "publisherUrl": info.publisher_url,
            "version": info.version,
            "start": info.start and info.start.isoformat(),
            "end": info.end and info.end.isoformat(),
        }
    if location := feed_location(stations):
        facts["location"] = location
        facts["placeTags"] = place_tags(stations)
    if place := feed_place(stations):
        facts["place"] = {
            "countryCode": place.country_code,
            "country": place.country,
            "region": place.region,
        }
    return facts


def scan_archive(
    archive: Archive, localities: Localities | None = None
) -> tuple[Summary, list[Located]]:
    """The summary and located stations of every route, trip and stop time."""
    if missing := archive.missing():
        raise MissingFiles(f"GTFS zip is missing {', '.join(missing)}")

    routes = 0
    route_types: set[int] = set()
    for (route_type,) in archive.values("routes", ("route_type",)):
        routes += 1
        try:
            value = parse_int(route_type)
        except ValueError:
            continue
        if value is not None:
            route_types.add(value)

    trips = 0
    service_ids: set[str] = set()
    for (service_id,) in archive.values("trips", ("service_id",)):
        trips += 1
        service_ids.add(service_id)

    stop_times: Counter[str] = Counter(
        stop_id for (stop_id,) in archive.values("stop_times", ("stop_id",))
    )
    stops = read_stops(archive)
    agencies = read_agencies(archive)
    feed_info = read_feed_info(archive)
    start, end = service_range(
        read_calendars(archive, service_ids),
        read_calendar_dates(archive, service_ids),
    )
    try:
        languages = feed_languages(
            feed_info.lang if feed_info else "",
            [agency.lang for agency in agencies.values()],
            (code.strip() for (code,) in archive.values("translations", ("language",))),
        )
    except ValueError:
        languages = None

    summary = Summary(
        agencies=tuple(agencies.values()),
        feed_info=feed_info,
        routes=routes,
        route_types=frozenset(route_types),
        stops=len(stops),
        trips=trips,
        start=start,
        end=end,
        languages=languages,
    )
    return summary, locate(station_weights(stops, stop_times), localities)


def scan(path: Path, localities: Localities | None = None) -> dict[str, Any]:
    """The facts of the whole zip at `path`, with municipality tags when
    `localities` is given. Raises MissingFiles, or the error of a member that
    cannot be read."""
    with path.open("rb") as handle:
        size, sha256 = zip_digest(handle)
        with open_zip(handle) as raw:
            summary, stations = scan_archive(Archive(raw), localities)
    return feed_facts(size, sha256, summary, False, stations)
