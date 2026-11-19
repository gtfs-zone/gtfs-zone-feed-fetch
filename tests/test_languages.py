import pytest

from gtfs_zone_feed_fetch.languages import FeedLanguages, feed_languages, normalize


def test_normalize():
    assert normalize("EN") == "en"
    assert normalize("en-US") == "en"
    assert normalize("ja_JP") == "ja"
    assert normalize("zh-Hant-TW") == "zh-Hant"
    assert normalize(" fr ") == "fr"
    # Library feeds: La Union (spa), cross-solution ("de"), Japanese towns
    # (ja-hrkt), TransLink North Vancouver (hur, no CLDR locale data).
    assert normalize("spa") == "es"
    assert normalize('"de"') == "de"
    assert normalize("ja-hrkt") == "ja-Hrkt"
    assert normalize("hur") == "hur"


@pytest.mark.parametrize("code", ["", "xx", "english", "mul", "ja-Abcd", "e n"])
def test_normalize_unknown_raises(code):
    with pytest.raises(ValueError, match="unknown language code"):
        normalize(code)


def test_no_language_is_en():
    assert feed_languages("", [], []) == FeedLanguages(default="en", offered=("en",))


def test_agency_lang_without_feed_lang():
    assert feed_languages("", ["", "it"], []) == FeedLanguages("it", ("it",))


def test_feed_lang_over_agency_lang():
    assert feed_languages("fr", ["de"], []) == FeedLanguages("fr", ("fr", "de"))


def test_mul_takes_agency_lang_then_translations():
    assert feed_languages("mul", ["nl"], ["fr", "nl"]) == FeedLanguages(
        "nl", ("nl", "fr")
    )
    assert feed_languages("MUL", [], ["fr", "nl", "fr"]) == FeedLanguages(
        "fr", ("fr", "nl")
    )


def test_mul_without_any_language_raises():
    with pytest.raises(ValueError, match="mul"):
        feed_languages("mul", [], [""])


def test_kana_readings_are_not_page_languages():
    assert feed_languages("ja", [], ["ja-Hrkt", "en", "ja-Latn"]) == FeedLanguages(
        "ja", ("ja", "en"), ("ja-Hrkt", "ja-Latn")
    )


def test_unknown_codes_are_listed_not_offered():
    assert feed_languages("", ["english"], ["xx-yy", "en"]) == FeedLanguages(
        "en", ("en",), unknown=("english", "xx-yy")
    )
    assert feed_languages("english", ["fr"], []) == FeedLanguages(
        "fr", ("fr",), unknown=("english",)
    )
