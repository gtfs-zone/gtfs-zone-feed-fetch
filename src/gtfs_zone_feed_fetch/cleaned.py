"""A hash of what a GTFS feed says, not how it is packaged.

Every GTFS reference file but feed_info.txt counts. A row is its values in
column-name order and a table is its column names plus the sum of its row
digests, so column order, row order, BOM, CRLF, quoting, zip layout and
feed_info leave the hash unchanged; ids are kept. A different column set, even
one more blank column, gives a different hash: two feeds join only when every
table says the same. The sum streams and keeps nothing per row."""

import hashlib
from operator import itemgetter

# GTFS reference files hashed; feed_info.txt describes the export, not the data.
CLEANED_TABLES = frozenset(
    {
        "agency",
        "stops",
        "routes",
        "trips",
        "stop_times",
        "calendar",
        "calendar_dates",
        "fare_attributes",
        "fare_rules",
        "timeframes",
        "rider_categories",
        "fare_media",
        "fare_products",
        "fare_leg_rules",
        "fare_leg_join_rules",
        "fare_transfer_rules",
        "areas",
        "stop_areas",
        "networks",
        "route_networks",
        "shapes",
        "frequencies",
        "transfers",
        "pathways",
        "levels",
        "location_groups",
        "location_group_stops",
        "booking_rules",
        "translations",
        "attributions",
    }
)

MODULUS = 1 << 128


class TableDigest:
    """Order-independent digest of one table's rows."""

    def __init__(self, header: list[str]) -> None:
        # Column indexes by name, so the row text is the same whatever the order.
        named = sorted((name, i) for i, name in enumerate(header) if name)
        self.columns = "\x1f".join(name for name, _ in named)
        self._indexes = [i for _, i in named]
        self._pick = itemgetter(*self._indexes) if named else None
        self.rows = 0
        self.total = 0
        self.done = False

    def add(self, row: list[str]) -> None:
        if self._pick is None:
            return
        try:
            values = self._pick(row)
        except IndexError:
            # A short row: its missing trailing fields read as empty.
            values = tuple(row[i] if i < len(row) else "" for i in self._indexes)
        if isinstance(values, str):
            values = (values,)
        text = "\x1f".join(values)
        if not text.strip("\x1f \t"):
            return
        digest = hashlib.blake2b(text.encode(), digest_size=16).digest()
        self.total += int.from_bytes(digest)
        self.rows += 1


class Cleaned:
    """Table digests gathered while an `Archive` is read."""

    def __init__(self) -> None:
        self.tables: dict[str, TableDigest] = {}

    def start(self, table: str, header: list[str]) -> TableDigest | None:
        """A fresh digest for `table`, or None when it is not hashed or a
        complete read already digested it."""
        if table not in CLEANED_TABLES:
            return None
        found = self.tables.get(table)
        if found is not None and found.done:
            return None
        self.tables[table] = TableDigest(header)
        return self.tables[table]

    def pending(self, present: set[str]) -> list[str]:
        """Hashed tables in `present` without a complete digest."""
        return sorted(
            table
            for table in present & CLEANED_TABLES
            if not (found := self.tables.get(table)) or not found.done
        )

    def hexdigest(self) -> str:
        """sha256 over every complete, non-empty table digest."""
        lines = sorted(
            f"{table}:{digest.columns}:{digest.rows}:{digest.total % MODULUS:032x}"
            for table, digest in self.tables.items()
            if digest.done and digest.rows
        )
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()
