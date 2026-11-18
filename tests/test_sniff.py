from conftest import fixture_zip

from gtfs_zone_feed_fetch.sniff import sniff


def test_sniff():
    assert sniff(fixture_zip("branching")[:512]) == "zip"
    assert sniff(b"") == "empty"
    assert sniff(b"  \n<!DOCTYPE html><html>") == "html"
    assert sniff(b"<head></head><html>") == "html"
    assert sniff(b'{"error": 1}') == "json"
    assert sniff(b"<?xml version='1.0'?><Error/>") == "xml"
    assert sniff(b"route_id,agency_id") == "unknown"
