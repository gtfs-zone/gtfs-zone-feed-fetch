"""Write the locality file `gtfs_zone_feed_fetch.localities` reads, from an
Overture Maps release's `division_area` parquet (local files or S3).

    uv run --extra localities scripts/localities.py [release] localities.parquet

The release defaults to the latest one.
"""

import sys

from gtfs_zone_feed_fetch.localities import (
    build,
    latest_overture_release,
    overture_source,
)


def main(*args: str) -> None:
    *release, out = args
    release = release[0] if release else latest_overture_release()
    rows = build(overture_source(release), out)
    print(f"{rows} localities from {release} in {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
