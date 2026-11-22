import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from pyarrow.fs import LocalFileSystem, SubTreeFileSystem

from gtfs_zone_feed_fetch.localities import (
    Localities,
    Locality,
    groups_holding,
    latest_overture_release,
)
from gtfs_zone_feed_fetch.places import Located, place_tags


def write_localities(path, rows):
    """A locality file of (name, name_en, country, polygon) rows."""
    shapes = [shape for *_, shape in rows]
    bounds = shapely.bounds(shapes)
    pq.write_table(
        pa.table(
            {
                "name": [r[0] for r in rows],
                "name_en": [r[1] for r in rows],
                "country": [r[2] for r in rows],
                "xmin": bounds[:, 0],
                "ymin": bounds[:, 1],
                "xmax": bounds[:, 2],
                "ymax": bounds[:, 3],
                "geometry": shapely.to_wkb(shapes),
            }
        ),
        path,
        row_group_size=1,
    )
    return Localities(path)


ARAKAWA = Locality("荒川区", "Arakawa", "JP")
BOSTON = Locality("Boston", "", "US")


def test_containing(tmp_path):
    localities = write_localities(
        tmp_path / "l.parquet",
        [
            ("荒川区", "Arakawa", "JP", shapely.box(139.7, 35.7, 139.8, 35.8)),
            ("Boston", "Boston", "US", shapely.box(-71.2, 42.2, -71.0, 42.4)),
            # Its bbox holds the Boston station, its shape does not.
            (
                "Ring",
                None,
                "US",
                shapely.box(-72, 42, -70, 43).difference(
                    shapely.box(-71.5, 42.1, -70.5, 42.9)
                ),
            ),
        ],
    )
    assert localities.containing([(35.75, 139.75), (42.3, -71.1), (0, 0)]) == [
        (ARAKAWA,),
        (BOSTON,),
        (),
    ]
    assert localities.containing([]) == []


def station(weight, *localities):
    return Located(0, 0, weight, "", "Japan", "JP", localities)


def test_municipalities_by_stop_times_with_english_names():
    sumida = Locality("墨田区", "Sumida", "JP")
    tags = place_tags([station(1, ARAKAWA), station(5, sumida), station(2, ARAKAWA)])
    assert tags["municipalities"] == ["墨田区", "Sumida", "荒川区", "Arakawa"]


def test_no_municipalities_without_localities():
    assert "municipalities" not in place_tags([station(1)])


def test_only_row_groups_holding_a_station_are_read(tmp_path):
    localities = write_localities(
        tmp_path / "l.parquet",
        [
            ("荒川区", "Arakawa", "JP", shapely.box(139.7, 35.7, 139.8, 35.8)),
            ("Boston", None, "US", shapely.box(-71.2, 42.2, -71.0, 42.4)),
        ],
    )
    source = pq.ParquetFile(localities.path)
    tree = shapely.STRtree(shapely.points([139.75], [35.75]))
    assert groups_holding(source, tree) == [0]


def test_latest_overture_release_is_the_greatest_directory(tmp_path):
    release = tmp_path / "overturemaps-us-west-2" / "release"
    for name in ("2026-09-17.0", "2026-11-18.0", "2026-10-22.1"):
        (release / name).mkdir(parents=True)
    (release / "2027-readme.txt").write_text("")
    filesystem = SubTreeFileSystem(str(tmp_path), LocalFileSystem())
    assert latest_overture_release(filesystem) == "2026-11-18.0"
