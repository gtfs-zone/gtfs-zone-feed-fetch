"""The languages a feed is published in, from feed_info, agency and
translations.txt. No I/O."""

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from babel import Locale
from babel.core import get_global, parse_locale

# feed_lang for a feed whose text mixes languages, given per row in
# translations.txt.
MULTIPLE = "mul"

# CLDR's language codes, less those naming no one language (multiple,
# undetermined, no linguistic content, uncoded), its script codes and its
# aliases (`spa` -> `es`, `iw` -> `he`).
LANGUAGES = frozenset(Locale("en").languages) - {MULTIPLE, "und", "zxx", "mis"}
SCRIPTS = frozenset(Locale("en").scripts)
ALIASES: dict[str, str] = get_global("language_aliases")
# Codes that write a reading of a language's text, not a language of their
# own, so they get no page set: Japanese names in kana (17 of 21 measured
# Japanese feeds) and in romaji (Muroto's agency name, f-0191bb2ecd).
READINGS = frozenset({"ja-Hrkt", "ja-Latn"})


@dataclass(frozen=True, slots=True)
class FeedLanguages:
    default: str
    # Every language the feed has text in, the default first, then sorted.
    offered: tuple[str, ...]
    # Readings of the feed's text in another script (`ja-Hrkt`, `ja-Latn`),
    # sorted.
    readings: tuple[str, ...] = ()
    # Codes the feed gives that `normalize` does not understand, as given.
    unknown: tuple[str, ...] = ()


def is_reading(code: str) -> bool:
    """Whether a normalized code is a reading (`ja-Hrkt`, `ja-Latn`)."""
    return code in READINGS


def normalize(code: str) -> str:
    """A GTFS language code as a BCP 47 tag: CLDR's language code in lowercase,
    the script in title case, the region dropped (`EN` -> `en`, `spa` -> `es`,
    `pl-PL` -> `pl`, `ja-hrkt` -> `ja-Hrkt`, `zh-Hant-TW` -> `zh-Hant`).
    Surrounding double quotes are dropped. Raises ValueError for a language or
    script CLDR does not name."""
    text = code.strip().strip('"').replace("_", "-")
    try:
        language, _, script, _ = parse_locale(text, sep="-")
    except ValueError as error:
        raise ValueError(f"unknown language code {code!r}") from error
    language = ALIASES.get(language, language)
    if language not in LANGUAGES or (script and script not in SCRIPTS):
        raise ValueError(f"unknown language code {code!r}")
    return f"{language}-{script}" if script else language


@cache
def known(code: str) -> str | None:
    """`normalize` of the code, None when it is not understood."""
    try:
        return normalize(code)
    except ValueError:
        return None


def feed_languages(
    feed_lang: str, agency_langs: Iterable[str], translated: Iterable[str]
) -> FeedLanguages:
    """The default language is feed_lang, else the first agency_lang, else
    `en`; with feed_lang `mul`, the first agency_lang, else the first
    translations.txt language. Offered is the default plus every agency_lang and
    translations.txt language, less readings (`ja-Hrkt`, `ja-Latn`), which go in
    `readings`. `agency_langs` and `translated` are the codes as the feed gives
    them, in order; empty ones are skipped (Hofbus and Kajaani have
    translations.txt rows with every field empty). Codes not understood are
    left out and listed in `unknown`."""
    agency_given = list(agency_langs)
    translated_given = list(dict.fromkeys(translated))
    unknown = tuple(
        code
        for code in dict.fromkeys([feed_lang, *agency_given, *translated_given])
        if code and code.lower() != MULTIPLE and known(code) is None
    )
    agency = [code for given in agency_given if given and (code := known(given))]
    translations = [
        code for given in translated_given if given and (code := known(given))
    ]
    if feed_lang.lower() == MULTIPLE:
        candidates = [*agency, *translations]
        if not candidates:
            raise ValueError("feed_lang is mul with no agency_lang or translations")
        default = candidates[0]
    elif feed_lang and (code := known(feed_lang)):
        default = code
    else:
        default = agency[0] if agency else "en"
    codes = {*agency, *translations} - {default}
    readings = {code for code in codes if is_reading(code)}
    return FeedLanguages(
        default=default,
        offered=(default, *sorted(codes - readings)),
        readings=tuple(sorted(readings)),
        unknown=unknown,
    )
