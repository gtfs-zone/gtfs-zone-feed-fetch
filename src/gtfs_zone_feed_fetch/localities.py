"""The localities containing a feed's stations, for the municipality place tags.

The data is Overture Maps' `division_area` rows of subtype `locality`, derived
from OpenStreetMap, in a parquet file written by `build`: one
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
from pyarrow.fs import FileSelector, FileSystem, FileType, S3FileSystem

ATTRIBUTION = (
    "Municipalities: Overture Maps Foundation, from OpenStreetMap contributors (ODbL)"
)

# Overture's public bucket: one prefix per release under `release/`.
OVERTURE_BUCKET = "overturemaps-us-west-2"
OVERTURE_REGION = "us-west-2"
# Rows per row group: a bbox filter skips whole groups by their min / max stats.
ROW_GROUP = 2000
WORLD = "{'min_x': -180, 'min_y': -90, 'max_x': 180, 'max_y': 90}::BOX_2D"

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

    @classmethod
    def s3(
        cls, path: str, endpoint: str, access_key: str, secret_key: str, region: str
    ) -> "Localities":
        """The file at `path` (`<bucket>/<key>`) on an S3 endpoint, with the
        bucket in the path (Garage)."""
        filesystem = S3FileSystem(
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            endpoint_override=endpoint,
            scheme="http" if endpoint.startswith("http://") else "https",
            force_virtual_addressing=False,
        )
        return cls(path, filesystem)

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
                # One thread: each Arrow thread's malloc arena reserves
                # address space, and a group is small.
                table = source.read_row_group(group, columns=COLUMNS, use_threads=False)
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


def latest_overture_release(filesystem: FileSystem | None = None) -> str:
    """The greatest release name under Overture's `release/` prefix (names are
    dates, `2026-11-18.0`), read anonymously unless `filesystem` is given."""
    filesystem = filesystem or S3FileSystem(anonymous=True, region=OVERTURE_REGION)
    infos = filesystem.get_file_info(FileSelector(f"{OVERTURE_BUCKET}/release"))
    return max(i.base_name for i in infos if i.type == FileType.Directory)


def overture_source(release: str) -> str:
    """The glob of a release's `division_area` parquet files."""
    return (
        f"s3://{OVERTURE_BUCKET}/release/{release}"
        "/theme=divisions/type=division_area/*.parquet"
    )


def build(
    source: str,
    out: Path | str,
    workdir: Path | str | None = None,
    memory_limit: str | None = None,
) -> int:
    """Write the locality file to `out` from Overture `division_area` parquet
    at `source` (local or `s3://`) and return its row count. duckdb (the
    `localities` extra) keeps its extensions and spill files in `workdir` and
    stays under `memory_limit` (duckdb syntax, `4GB`) when given."""
    import duckdb

    con = duckdb.connect()
    if memory_limit is not None:
        con.execute(f"SET memory_limit = '{memory_limit}'")
    if workdir is not None:
        con.execute(f"SET extension_directory = '{Path(workdir) / 'duckdb'}'")
        con.execute(f"SET temp_directory = '{Path(workdir) / 'duckdb-tmp'}'")
    for extension in ("httpfs", "spatial"):
        con.install_extension(extension)
        con.load_extension(extension)
    con.execute(f"SET s3_region = '{OVERTURE_REGION}'")
    query = f"""
        SELECT names.primary AS name, names.common['en'] AS name_en, country,
            bbox.xmin AS xmin, bbox.ymin AS ymin, bbox.xmax AS xmax, bbox.ymax AS ymax,
            ST_AsWKB(geometry::GEOMETRY) AS geometry
        FROM read_parquet('{source}')
        WHERE subtype = 'locality' AND class = 'land'
        ORDER BY ST_Hilbert(ST_Centroid(geometry::GEOMETRY), {WORLD})
    """
    con.execute(
        f"COPY ({query}) TO '{out}'"
        f" (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP})"
    )
    (rows,) = con.execute(f"SELECT count(*) FROM '{out}'").fetchone()
    return rows
