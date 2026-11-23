from gtfs_zone_feed_fetch.urls import is_absolute, normalize_url


def test_normalize_url_folds_case_default_ports_and_query_order():
    assert normalize_url("HTTPS://Example.ORG:443/Feed.zip?b=2&a=1") == (
        "https://example.org/Feed.zip?a=1&b=2"
    )
    assert normalize_url("https://example.org/feed.zip/") == (
        "https://example.org/feed.zip"
    )
    assert normalize_url("https://example.org:8443/f#x") == (
        "https://example.org:8443/f"
    )
    # http and https stay distinct.
    assert normalize_url("http://example.org/f") != normalize_url(
        "https://example.org/f"
    )


def test_normalize_url_is_empty_without_a_host():
    assert normalize_url("/amtrak/vehicle_positions.pb") == ""
    assert normalize_url("https://[bad/f") == ""
    assert not is_absolute("example.org/f.zip")
    assert is_absolute(" HTTP://example.org/f.zip")
