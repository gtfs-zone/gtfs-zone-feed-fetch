"""Where a feed runs, from one offline reverse-geocoding pass over its stations.

Each station with stop times is matched to its nearest place in
`reverse_geocode`'s bundled GeoNames data, for its ADM1 region and country,
and weighted by its stop times. From that pass:
- `feed_place`: a region with at least `SHARE` of the stop times names the
  feed; otherwise a country with that share does; otherwise nothing does.
- `feed_location`: the stations' bbox, stop-time weighted center and count.
- `place_tags`: every country and region the stations are in and, given
  `Localities`, the `MUNICIPALITIES` localities with the most stop times, for
  search.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

import reverse_geocode

from gtfs_zone_feed_fetch.localities import Localities, Locality
from gtfs_zone_feed_fetch.reader import Stop

SHARE = 0.8
MUNICIPALITIES = 25


@dataclass(frozen=True, slots=True)
class Place:
    # Empty for a feed named by its country alone.
    region: str
    country: str
    country_code: str
    # The stop-time weighted center of the feed's stations in the place.
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Located:
    """A station with stop times and the region and country it is in."""

    lat: float
    lon: float
    # Stop times at the station.
    weight: int
    # ADM1; empty where GeoNames has none.
    region: str
    country: str
    country_code: str
    # The localities the station is in; empty when none were looked up.
    localities: tuple[Locality, ...] = ()


def station_weights(
    stops: Mapping[str, Stop], stop_times: Mapping[str, int]
) -> dict[tuple[float, float], int]:
    """Stop times per located station, by its coordinates. `stop_times` is the
    count per stop_id; a stop counts for its parent station when the feed has
    it."""
    counts: Counter[str] = Counter()
    for stop_id, n in stop_times.items():
        stop = stops.get(stop_id)
        if stop is not None and stop.parent_station in stops:
            stop_id = stop.parent_station
        counts[stop_id] += n
    weights: Counter[tuple[float, float]] = Counter()
    for stop_id, n in counts.items():
        stop = stops.get(stop_id)
        if stop is not None and stop.lat is not None and stop.lon is not None:
            weights[stop.lat, stop.lon] += n
    return weights


def locate(
    weights: Mapping[tuple[float, float], int], localities: Localities | None = None
) -> list[Located]:
    """Every located station with stop times, reverse-geocoded, from
    `station_weights`, with the localities it is in when `localities` is given."""
    points = list(weights)
    if not points:
        return []
    found = reverse_geocode.search(points)
    within = localities.containing(points) if localities else [()] * len(points)
    return [
        Located(
            lat=lat,
            lon=lon,
            weight=weights[lat, lon],
            region=place.get("state", ""),
            country=place["country"],
            country_code=place["country_code"],
            localities=inside,
        )
        for (lat, lon), place, inside in zip(points, found, within, strict=True)
    ]


def center(stations: list[Located]) -> tuple[float, float]:
    """The stop-time weighted center, as lat, lon."""
    weight = sum(s.weight for s in stations)
    return (
        round(sum(s.lat * s.weight for s in stations) / weight, 5),
        round(sum(s.lon * s.weight for s in stations) / weight, 5),
    )


def feed_place(stations: list[Located]) -> Place | None:
    """The feed's region, else its country, else None."""
    if not stations:
        return None
    total = sum(s.weight for s in stations)
    regions: Counter[tuple[str, str, str]] = Counter()
    for s in stations:
        regions[s.country_code, s.country, s.region] += s.weight
    countries: Counter[tuple[str, str]] = Counter()
    for (code, country, _), n in regions.items():
        countries[code, country] += n

    (code, country, region), n = regions.most_common(1)[0]
    if not region or n < SHARE * total:
        (code, country), n = countries.most_common(1)[0]
        region = ""
        if n < SHARE * total:
            return None
    lat, lon = center(
        [
            s
            for s in stations
            if s.country_code == code and (not region or s.region == region)
        ]
    )
    return Place(region=region, country=country, country_code=code, lat=lat, lon=lon)


def feed_location(stations: list[Located]) -> dict | None:
    """The stations' bbox (min lon, min lat, max lon, max lat), weighted center
    (lat, lon) and count, for the content report."""
    if not stations:
        return None
    lats = [s.lat for s in stations]
    lons = [s.lon for s in stations]
    return {
        "bbox": [
            round(min(lons), 5),
            round(min(lats), 5),
            round(max(lons), 5),
            round(max(lats), 5),
        ],
        "center": list(center(stations)),
        "stations": len(stations),
    }


def ranked(weights: Counter[str]) -> list[str]:
    """Names by stop times, most first, then by name."""
    return [name for name, _ in sorted(weights.items(), key=lambda i: (-i[1], i[0]))]


def place_tags(stations: list[Located]) -> dict[str, list[str]]:
    """The countries and regions the stations are in, each by stop times, most
    first, and the names of the `MUNICIPALITIES` localities with the most stop
    times, each name then its English name, when localities were looked up."""
    countries: Counter[str] = Counter()
    regions: Counter[str] = Counter()
    localities: Counter[Locality] = Counter()
    for s in stations:
        countries[s.country] += s.weight
        if s.region:
            regions[s.region] += s.weight
        for locality in s.localities:
            localities[locality] += s.weight
    tags = {"countries": ranked(countries), "regions": ranked(regions)}
    if localities:
        top = sorted(localities.items(), key=lambda i: (-i[1], i[0].name))
        names = (
            name
            for locality, _ in top[:MUNICIPALITIES]
            for name in (locality.name, locality.name_en)
            if name
        )
        tags["municipalities"] = list(dict.fromkeys(names))
    return tags


def place_label(
    place: Place | None, site_title: str, locality: str | None = None
) -> str:
    """'Texas', 'United States' or 'Quesnel, British Columbia', leaving out
    what the site title already names."""
    title = site_title.casefold()
    parts = []
    if locality and locality.casefold() not in title:
        parts.append(locality)
    area = (place.region or place.country) if place else ""
    if (
        area
        and area.casefold() not in title
        and area.casefold() != (locality or "").casefold()
    ):
        parts.append(area)
    return ", ".join(parts)
