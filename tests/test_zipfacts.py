import zipfile

from conftest import fixture_files, make_zip

from gtfs_zone_feed_fetch.zipfacts import read_zipfacts


def test_zipfacts_finds_the_root(tmp_path):
    files = {f"feed/{name}": body for name, body in fixture_files("branching").items()}
    path = tmp_path / "feed.zip"
    path.write_bytes(make_zip({**files, "__MACOSX/stops.txt": "", "readme/": ""}))
    facts = read_zipfacts(path)
    assert facts.root == "feed/"
    assert facts.member("stops.txt").name == "feed/stops.txt"
    assert facts.member("shapes.txt") is None
    assert facts.uncompressed_bytes() == sum(len(b) for b in files.values())
    assert all(entry.method == zipfile.ZIP_STORED for entry in facts.files)
