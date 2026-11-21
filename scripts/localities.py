"""Write the locality file `gtfs_zone_feed_fetch.localities` reads, from an
Overture Maps release's `division_area` parquet (local files or S3).

    release=s3://overturemaps-us-west-2/release/2026-11-18.0
    uv run --group localities scripts/localities.py \
        "$release/theme=divisions/type=division_area/*.parquet" \
        localities-2026-11-18.0.parquet
"""

import sys

import duckdb

# Rows per row group: a bbox filter skips whole groups by their min / max stats.
ROW_GROUP = 2000
WORLD = "{'min_x': -180, 'min_y': -90, 'max_x': 180, 'max_y': 90}::BOX_2D"


def main(source: str, out: str) -> None:
    con = duckdb.connect()
    for extension in ("httpfs", "spatial"):
        con.install_extension(extension)
        con.load_extension(extension)
    con.execute("SET s3_region = 'us-west-2'")
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
    print(f"{rows} localities in {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
