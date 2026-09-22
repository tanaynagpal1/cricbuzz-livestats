"""
Data provenance and coverage — the single source of truth.

Both the Streamlit app and the project documentation read from this module,
so a coverage claim cannot be correct in one place and stale in the other.
A number that appears in two files will eventually disagree with itself.

Every figure here is either measured from our own data or stated by the
source, and each one says which. Nothing is estimated.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

SOURCES = {
    "historical": {
        "name": "Cricsheet",
        "url": "https://cricsheet.org/",
        "what": "Ball-by-ball JSON for every ODI and T20 international in its archive",
        "licence": "Open data, free to use with attribution",
        "retrieved": "2026-09-16",
    },
    "live": {
        "name": "Cricbuzz Cricket API (via RapidAPI)",
        "url": "https://rapidapi.com/cricketapilive/api/cricbuzz-cricket",
        "what": "Live, recent and upcoming matches; top-statistics leaderboards",
        "licence": "Free tier, 700 requests/month",
        "retrieved": "read live, never stored",
    },
    "venue_capacity": {
        "name": "Wikipedia — List of cricket grounds by capacity",
        "url": "https://en.wikipedia.org/wiki/List_of_cricket_grounds_by_capacity",
        "what": "Ground capacities, frozen into etl/reference/venue_capacity.csv",
        "licence": "CC BY-SA",
        "retrieved": "2026-09-17",
    },
}

# --------------------------------------------------------------------------
# what the warehouse holds  (measured from our own parquet files)
# --------------------------------------------------------------------------

ARCHIVE = {
    "matches": 8_911,
    "batting_rows": 147_503,
    "bowling_rows": 106_534,
    "players": 8_138,
    "venues": 367,
    "teams": 200,
    "series_editions": 1_497,
    "first_match": "2002-06-27",
    "last_match": "2026-09-17",
    "mens_matches": 6_129,
    "womens_matches": 2_782,
}

# The same archive split by format. Men's + women's = matches in each row.
BY_FORMAT = {
    "ODI":  {"matches": 3_182, "mens": 2_571, "womens": 611,
             "first_match": "2002-06-27", "last_match": "2026-09-09"},
    "T20I": {"matches": 5_729, "mens": 3_558, "womens": 2_171,
             "first_match": "2005-02-17", "last_match": "2026-09-17"},
}

# --------------------------------------------------------------------------
# what it does NOT hold, and why
# --------------------------------------------------------------------------

# Stated by Cricsheet, not estimated by us. Cricsheet gives this figure for
# ODIs; for T20Is it publishes only an all-formats total (329 matches), so
# the coverage percentage below is stated for ODIs alone.
WITHHELD_ODIS = 159
WITHHELD_ALL_FORMATS = 329
ODIS_IN_SOURCE_WINDOW = BY_FORMAT["ODI"]["matches"] + WITHHELD_ODIS   # 3,341
COVERAGE = BY_FORMAT["ODI"]["matches"] / ODIS_IN_SOURCE_WINDOW        # 0.952

EXCLUSIONS = [
    {
        "what": "All matches involving Afghanistan",
        "count": (f"{WITHHELD_ODIS} ODIs, plus T20Is "
                  f"({WITHHELD_ALL_FORMATS} matches across all formats)"),
        "why": (
            "Cricsheet withheld every Afghanistan match on 14 November 2024, "
            "in protest at Afghan women players being excluded from the game. "
            "The matches were played; the source does not publish them."
        ),
        "url": ("https://cricsheet.org/article/"
                "explanation-for-withholding-of-afghanistani-matches/"),
        "effect": (
            "Afghanistan does not appear in any team, player or head-to-head "
            "result. Every other figure is unaffected."
        ),
    },
    {
        "what": "ODIs before 2002",
        "count": "not covered by the source",
        "why": (
            "Cricsheet's ODI coverage only becomes dense from 2002. Earlier "
            "matches carry no delivery data, so no batting or bowling row can "
            "be derived from them. T20Is are covered from February 2005, the "
            "first men's T20I."
        ),
        "url": None,
        "effect": (
            "All-time career totals are career totals SINCE 2002, which is "
            "stated wherever a leaderboard is shown."
        ),
    },
    {
        "what": "Domestic and franchise cricket",
        "count": "excluded by design",
        "why": "Internationals only, to keep the database inside the free tier.",
        "url": None,
        "effect": "IPL, BBL and similar competitions are out of scope.",
    },
    {
        "what": "Super-over innings",
        "count": "116 super-over innings",
        "why": (
            "A super over is a tie-break, not an innings. Counting it would "
            "give those players an extra dismissal and permanently lower "
            "their batting average."
        ),
        "url": None,
        "effect": (
            "The matches are present with their result (e.g. \"won the "
            "super over\"); the super-over deliveries are not."
        ),
    },
]

# --------------------------------------------------------------------------
# known limitations of derived columns
# --------------------------------------------------------------------------

CAVEATS = [
    {
        "field": "venue.capacity",
        "note": (
            "Current capacity as of September 2026, not capacity on the day "
            "of the match. Grounds are rebuilt — Eden Gardens held 100,000 "
            "before its 2011 renovation. 171 of 367 venues have no published "
            "figure (mostly smaller T20I grounds) and are left blank rather "
            "than estimated."
        ),
    },
    {
        "field": "player.playing_role",
        "note": (
            "Derived from behaviour, not declared: bowling share, average "
            "batting position, and catches plus stumpings per match. It is a "
            "reasonable classification, not an official one — AB de Villiers "
            "reads as a wicket-keeper because he kept in many matches. Roles are "
            "derived across ODIs and T20Is together."
        ),
    },
    {
        "field": "player.batting_style / bowling_style",
        "note": (
            "Not present in any free ball-by-ball source. Left NULL rather "
            "than guessed."
        ),
    },
    {
        "field": "match.toss advantage (Q17)",
        "note": (
            "263 matches ended with no winner (145 ODIs, 118 T20Is) — no "
            "result, tie, or abandoned. "
            "They are excluded from the toss-advantage denominator, because a "
            "match with no winner cannot show whether the toss helped."
        ),
    },
    {
        "field": "bowling.balls_bowled",
        "note": (
            "Counted from actual deliveries, not from overs x 6, so a "
            "miscounted over (124 ODIs carry one) correctly produces 61 "
            "legal balls rather than 60. One spell in the archive records 11 "
            "overs in a 50-over innings, which is not legal cricket - "
            "EJ Carson, New Zealand v Sri Lanka, 30 June 2023. The source "
            "file genuinely says so; it is carried unchanged rather than "
            "corrected to a number we would have invented."
        ),
    },
]


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def coverage_headline() -> str:
    """One sentence, safe to put anywhere."""
    odi, t20 = BY_FORMAT["ODI"], BY_FORMAT["T20I"]
    return (
        f"{ARCHIVE['matches']:,} internationals: {odi['matches']:,} ODIs "
        f"({odi['first_match'][:4]}–{odi['last_match'][:4]}) and "
        f"{t20['matches']:,} T20Is ({t20['first_match'][:4]}–"
        f"{t20['last_match'][:4]}). The ODIs are {COVERAGE:.1%} of the "
        f"matches our source covers in that window."
    )


def coverage_markdown() -> str:
    """The full note, for the Home page and the README.

    Written as markdown so Streamlit renders it with st.markdown() and the
    README can include it unchanged.
    """
    lines = [
        "### Data coverage",
        "",
        coverage_headline(),
        "",
        "| | |",
        "|---|---|",
        f"| Matches | {ARCHIVE['matches']:,} "
        f"({ARCHIVE['mens_matches']:,} men's, {ARCHIVE['womens_matches']:,} women's) |",
        *[f"| {fmt} | {d['matches']:,} ({d['mens']:,} men's, "
          f"{d['womens']:,} women's) |" for fmt, d in BY_FORMAT.items()],
        f"| Player innings | {ARCHIVE['batting_rows']:,} batting, "
        f"{ARCHIVE['bowling_rows']:,} bowling |",
        f"| Players | {ARCHIVE['players']:,} |",
        f"| Venues | {ARCHIVE['venues']} |",
        f"| Date range | {ARCHIVE['first_match']} to {ARCHIVE['last_match']} |",
        "",
        "### What is not included",
        "",
    ]
    for e in EXCLUSIONS:
        head = f"**{e['what']}** — {e['count']}"
        if e["url"]:
            head += f" ([source]({e['url']}))"
        lines += [head, "", e["why"], "", f"*Effect:* {e['effect']}", ""]

    lines += ["### Known limitations", ""]
    for c in CAVEATS:
        lines += [f"**`{c['field']}`** — {c['note']}", ""]

    return "\n".join(lines)


if __name__ == "__main__":
    print(coverage_markdown())