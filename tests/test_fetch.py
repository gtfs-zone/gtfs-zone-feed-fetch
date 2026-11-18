import httpx
import respx
from conftest import fixture_zip

from gtfs_zone_feed_fetch.fetch import conditional_headers, fetch

URL = "https://example.org/gtfs.zip"
ZIP = fixture_zip("branching")


@respx.mock
def test_fetch_streams_and_hashes(tmp_path):
    respx.get(URL).respond(200, content=ZIP, headers={"ETag": '"v1"'})
    with httpx.Client() as client:
        out = fetch(client, URL, {}, tmp_path, 10_000_000)
    assert out.status == 200
    assert out.kind == "zip"
    assert out.etag == '"v1"'
    assert out.path.read_bytes() == ZIP


@respx.mock
def test_fetch_is_conditional(tmp_path):
    route = respx.get(URL).respond(304)
    headers = conditional_headers('"v1"', "Mon, 26 Oct 2026 10:00:00 GMT")
    with httpx.Client() as client:
        out = fetch(client, URL, headers, tmp_path, 10_000_000)
    assert out.status == 304
    assert out.path is None
    sent = route.calls.last.request.headers
    assert sent["If-None-Match"] == '"v1"'
    assert sent["If-Modified-Since"] == "Mon, 26 Oct 2026 10:00:00 GMT"
    assert conditional_headers(None, "") == {}


@respx.mock
def test_fetch_gives_up_on_huge_bodies(tmp_path):
    respx.get(URL).respond(200, content=ZIP)
    with httpx.Client() as client:
        out = fetch(client, URL, {}, tmp_path, 100)
    assert out.path is None
    assert out.error == "larger than 100 bytes"
    assert not list(tmp_path.iterdir())


@respx.mock
def test_fetch_reports_transport_errors(tmp_path):
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    with httpx.Client() as client:
        out = fetch(client, URL, {}, tmp_path, 100)
    assert out.status is None
    assert out.error == "ConnectError: refused"
