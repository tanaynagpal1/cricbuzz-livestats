"""Conversions between source data and the shapes this project uses.

Every function here exists because a real source got something wrong or
awkward. The docstrings say which.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Source vocabularies differ. Cricbuzz says "TEST" and "T20";
# Cricsheet says "Test" and "IT20". The 25 queries expect Test/ODI/T20I.
FORMAT_MAP = {
    "test": "Test",
    "odi": "ODI",
    "t20": "T20I",
    "t20i": "T20I",
    "it20": "T20I",
}


def to_utc(value) -> datetime | None:
    """Convert a Cricbuzz epoch value to a UTC datetime.

    Cricbuzz mixes units inside a single response: match dates arrive as
    13-digit milliseconds, responseLastUpdated as 10-digit seconds, and both
    as strings. Reading milliseconds as seconds raises; reading seconds as
    milliseconds silently returns a date in 1970, which is the dangerous one.

    Detecting the unit by digit count is safe here, though not in general:
    cricket dates span 1877-2030, and across that range seconds are always
    10 digits and milliseconds always 13. The ranges never overlap.
    """
    if value in (None, "", 0, "0"):
        return None

    number = int(value)

    if len(str(abs(number))) >= 13:
        number = number / 1000

    return datetime.fromtimestamp(number, tz=timezone.utc)


def overs_to_balls(overs) -> int | None:
    """Convert cricket overs notation to a true ball count.

    '3.4' means 3 overs and 4 balls = 22 balls, NOT 3.4 x 6 = 20.4.
    The digit after the point counts balls, not tenths.

    Never use the API's own 'balls' field: it is the overs figure with the
    decimal point deleted (3.4 becomes 34), which overstates by 55%.
    """
    if overs in (None, ""):
        return None

    overs = float(overs)
    whole = int(overs)
    part = round((overs - whole) * 10)

    return whole * 6 + part


def balls_to_overs(balls) -> str | None:
    """Convert a ball count back to cricket overs notation, for display."""
    if balls in (None, ""):
        return None

    balls = int(balls)
    return f"{balls // 6}.{balls % 6}"


def normalise_format(value) -> str | None:
    """Map any source's format vocabulary onto Test / ODI / T20I."""
    if not value:
        return None

    cleaned = str(value).strip()
    return FORMAT_MAP.get(cleaned.lower(), cleaned)


def safe_int(value, default=None) -> int | None:
    """Parse a value that may be an int, a numeric string, None or ''.

    Cricbuzz returns numbers as strings in several places - strkrate, overs
    and every timestamp field.
    """
    if value in (None, ""):
        return default

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def strike_rate(runs, balls) -> float | None:
    """Batting strike rate: runs per 100 balls.

    Computed here rather than taken from the API, whose strkrate arrives as
    a string. Returns None when no balls were faced - a batter can be run
    out without facing one, and 0/0 is not zero, it is unknown.
    """
    runs, balls = safe_int(runs), safe_int(balls)

    if not balls:
        return None

    return round(runs * 100 / balls, 2)


def economy(runs_conceded, balls_bowled) -> float | None:
    """Bowling economy: runs conceded per over.

    Computed from balls, never from the API's economy or rpb fields - both
    were wrong in the sample we checked (rpb said 0.78 where the real figure
    was 1.30, because it divided by the fake ball count).
    """
    runs, balls = safe_int(runs_conceded), safe_int(balls_bowled)

    if not balls:
        return None

    return round(runs * 6 / balls, 2)