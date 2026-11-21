"""The localities containing a feed's stations, for the municipality place tags.

The data is Overture Maps' `division_area` rows of subtype `locality`, derived
from OpenStreetMap, in a parquet file written by `scripts/localities.py`: one
row per locality with its primary and English names, country, bbox and WKB
geometry, sorted along a Hilbert curve so a bbox filter reads few row groups.
Only row groups meeting the stations' bbox are read, one at a time, and only
geometries whose bbox holds a station are parsed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.compute as pc
import pyarrow.dataset as ds
import shapely

ATTRIBUTION = (
    "Municipalities: Overture Maps Foundation, from OpenStreetMap contributors (ODbL)"
)

COLUMNS = ["name", "name_en", "country", "xmin", "ymin", "xmax", "ymax", "geometry"]


@dataclass(frozen=True, slots=True)
class Locality:
    name: str
    # Overture's English name; empty when it has none or it is `name`.
    name_en: str
    country: str


class Localities:
    """Lookups in the locality file at `path`."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def containing(
        self, points: Sequence[tuple[float, float]]
    ) -> list[tuple[Locality, ...]]:
        """The localities each (lat, lon) point is in or on the edge of."""
        found: list[list[Locality]] = [[] for _ in points]
        if not points:
            return []
        lats = np.array([p[0] for p in points])
        lons = np.array([p[1] for p in points])
        tree = shapely.STRtree(shapely.points(lons, lats))
        meets = (
            (pc.field("xmax") >= lons.min())
            & (pc.field("xmin") <= lons.max())
            & (pc.field("ymax") >= lats.min())
            & (pc.field("ymin") <= lats.max())
        )
        dataset = ds.dataset(self.path, format="parquet")
        for batch in dataset.to_batches(columns=COLUMNS, filter=meets):
            boxes = shapely.box(
                *(batch.column(c).to_numpy() for c in ("xmin", "ymin", "xmax", "ymax"))
            )
            rows, hits = tree.query(boxes)
            if not len(rows):
                continue
            parsed, at = np.unique(rows, return_inverse=True)
            shapes = shapely.from_wkb(
                batch.column("geometry").take(parsed).to_numpy(zero_copy_only=False)
            )
            inside = shapely.intersects_xy(shapes[at], lons[hits], lats[hits])
            names = batch.column("name").to_pylist()
            names_en = batch.column("name_en").to_pylist()
            countries = batch.column("country").to_pylist()
            for row, point in zip(rows[inside], hits[inside], strict=True):
                name = names[row] or ""
                en = names_en[row] or ""
                found[point].append(
                    Locality(name, "" if en == name else en, countries[row] or "")
                )
        return [tuple(f) for f in found]
