"""The localities containing a feed's stations, for the municipality place tags.

The data is Overture Maps' `division_area` rows of subtype `locality`, derived
from OpenStreetMap, in a parquet file written by `scripts/localities.py`: one
row per locality with its primary and English names, country, bbox and WKB
geometry, sorted along a Hilbert curve so each row group covers a small area.
Only row groups whose bounds hold a station are read, one at a time, and only
geometries whose bbox holds a station are parsed, so on a remote filesystem
(S3) a feed reads a small part of the file.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from pyarrow.fs import FileSystem

ATTRIBUTION = (
    "Municipalities: Overture Maps Foundation, from OpenStreetMap contributors (ODbL)"
)

BOUNDS = ("xmin", "ymin", "xmax", "ymax")
COLUMNS = ["name", "name_en", "country", *BOUNDS, "geometry"]


@dataclass(frozen=True, slots=True)
class Locality:
    name: str
    # Overture's English name; empty when it has none or it is `name`.
    name_en: str
    country: str


class Localities:
    """Lookups in the locality file at `path`, on `filesystem` when given."""

    def __init__(self, path: Path | str, filesystem: FileSystem | None = None) -> None:
        self.path = str(path)
        self.filesystem = filesystem

    def containing(
        self, points: Sequence[tuple[float, float]]
    ) -> list[tuple[Locality, ...]]:
        """The localities each (lat, lon) point is in or on the edge of."""
        if not points:
            return []
        found: list[list[Locality]] = [[] for _ in points]
        lats = np.array([p[0] for p in points])
        lons = np.array([p[1] for p in points])
        tree = shapely.STRtree(shapely.points(lons, lats))
        with pq.ParquetFile(
            self.filesystem.open_input_file(self.path) if self.filesystem else self.path
        ) as source:
            for group in groups_holding(source, tree):
                table = source.read_row_group(group, columns=COLUMNS)
                for row, point in rows_holding(table, tree, lats, lons):
                    name = table.column("name")[row].as_py() or ""
                    en = table.column("name_en")[row].as_py() or ""
                    country = table.column("country")[row].as_py() or ""
                    found[point].append(
                        Locality(name, "" if en == name else en, country)
                    )
        return [tuple(f) for f in found]


def groups_holding(source: pq.ParquetFile, tree: shapely.STRtree) -> list[int]:
    """The row groups whose bounds, from their column statistics, hold a point
    of `tree`."""
    meta = source.metadata
    index = {meta.schema.column(i).name: i for i in range(meta.num_columns)}
    bounds = []
    for group in range(meta.num_row_groups):
        columns = meta.row_group(group)
        stats = {c: columns.column(index[c]).statistics for c in BOUNDS}
        bounds.append(
            (stats["xmin"].min, stats["ymin"].min, stats["xmax"].max, stats["ymax"].max)
        )
    if not bounds:
        return []
    groups, _ = tree.query(shapely.box(*np.array(bounds).T))
    return sorted(set(groups.tolist()))


def rows_holding(
    table: pa.Table, tree: shapely.STRtree, lats: np.ndarray, lons: np.ndarray
) -> list[tuple[int, int]]:
    """(row, point) for each point of `tree` in or on the edge of a row's
    geometry. Only rows whose bbox holds a point are parsed."""
    boxes = shapely.box(*(table.column(c).to_numpy() for c in BOUNDS))
    rows, points = tree.query(boxes)
    if not len(rows):
        return []
    parsed, at = np.unique(rows, return_inverse=True)
    shapes = shapely.from_wkb(
        table.column("geometry").take(parsed).to_numpy(zero_copy_only=False)
    )
    inside = shapely.intersects_xy(shapes[at], lons[points], lats[points])
    return list(zip(rows[inside].tolist(), points[inside].tolist(), strict=True))
