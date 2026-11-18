"""A feed's first and last service dates from its calendars. No I/O."""

from collections.abc import Mapping
from datetime import date

from gtfs_zone_feed_fetch.reader import Calendar


def service_bounds(
    calendars: Mapping[str, Calendar],
    calendar_dates: Mapping[str, Mapping[date, bool]],
) -> dict[str, tuple[date, date]]:
    """service_id -> (calendar start, calendar end), widened by its added
    dates."""
    bounds = {sid: (c.start, c.end) for sid, c in calendars.items()}
    for service_id, exceptions in calendar_dates.items():
        added = [day for day, on in exceptions.items() if on]
        if not added:
            continue
        first, last = min(added), max(added)
        if service_id in bounds:
            start, end = bounds[service_id]
            first, last = min(start, first), max(end, last)
        bounds[service_id] = (first, last)
    return bounds


def service_range(
    calendars: Mapping[str, Calendar],
    calendar_dates: Mapping[str, Mapping[date, bool]],
) -> tuple[date | None, date | None]:
    """The first and last dates of every service."""
    bounds = service_bounds(calendars, calendar_dates).values()
    return (
        min((b[0] for b in bounds), default=None),
        max((b[1] for b in bounds), default=None),
    )
