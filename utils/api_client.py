"""Client for the Cricbuzz Cricket API (RapidAPI).

All network access to Cricbuzz goes through this module. Nothing else in
the project should import requests or know that an API key exists.

Responses are cached to disk with a per-endpoint TTL, because the free plan
allows only a few hundred requests per month.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterator

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "raw" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("RAPIDAPI_KEY")
API_HOST = os.getenv("RAPIDAPI_HOST", "cricbuzz-cricket.p.rapidapi.com")

TIMEOUT = 20

# How long a cached response stays fresh, in seconds. The live strip shows on
# every page, so live scores are kept for 2 minutes rather than 30 seconds:
# the quota is 200 calls a month, and a strip that refreshed on every click
# would spend it in a few days.
TTL_LIVE = 120
TTL_MATCH_LIST = 300
TTL_SCORECARD = 3600
TTL_REFERENCE = 86400
TTL_RECORDS = 7 * 86400   # career leaderboards change slowly: refresh weekly

# The API's own format codes, from the get-records filter block.
MATCH_TYPE_IDS = {"test": 1, "odi": 2, "t20": 3}


QUOTA_FILE = CACHE_DIR / "_quota.json"


class CricbuzzError(RuntimeError):
    """The API could not be reached, or returned something unusable."""


def _save_quota(response: requests.Response) -> None:
    """Remember how many calls RapidAPI says are left this month.

    RapidAPI adds two headers to every reply: the monthly limit and how many
    requests remain. Saving them lets the sidebar show real usage instead of
    a guess. Only real network calls reach here; cached answers cost nothing.
    """
    limit = response.headers.get("x-ratelimit-requests-limit")
    remaining = response.headers.get("x-ratelimit-requests-remaining")
    if limit is None or remaining is None:
        return
    try:
        QUOTA_FILE.write_text(json.dumps({
            "limit": int(limit),
            "remaining": int(remaining),
            "checked_at": time.time(),
        }), encoding="utf-8")
    except (OSError, ValueError):
        pass


def get_quota() -> dict | None:
    """The last quota RapidAPI reported, or None if no call has been made yet."""
    try:
        return json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_age(cache_name: str) -> float | None:
    """Seconds since a cached response was saved, or None if never."""
    path = _cache_path(cache_name)
    return time.time() - path.stat().st_mtime if path.exists() else None


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _read_cache(name: str, max_age: int) -> dict | None:
    """Return cached JSON if it exists and is younger than max_age seconds."""
    path = _cache_path(name)
    if not path.exists():
        return None

    if time.time() - path.stat().st_mtime > max_age:
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _write_cache(name: str, data: dict) -> None:
    """Save a response. A failed write must never break a working request."""
    try:
        _cache_path(name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _get(path: str, cache_name: str, max_age: int,
         params: dict | None = None) -> dict:
    """Fetch an endpoint, serving from the disk cache while it is fresh.

    Returns {} when the API legitimately has nothing to send (HTTP 204).
    Raises CricbuzzError for anything that is actually wrong.
    """
    cached = _read_cache(cache_name, max_age)
    if cached is not None:
        return cached

    if not API_KEY:
        raise CricbuzzError("RAPIDAPI_KEY is not set - check your .env file")

    url = f"https://{API_HOST}{path}"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": API_HOST}

    try:
        response = requests.get(url, headers=headers, params=params,
                                timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        raise CricbuzzError(f"Timed out after {TIMEOUT}s calling {path}") from None
    except requests.exceptions.RequestException as exc:
        raise CricbuzzError(f"Could not reach the API: {exc}") from None

    _save_quota(response)

    if response.status_code in (401, 403):
        raise CricbuzzError("API key rejected, or not subscribed to this API")
    if response.status_code == 429:
        raise CricbuzzError("Rate limited, or the monthly quota is exhausted")
    if response.status_code >= 400:
        raise CricbuzzError(f"HTTP {response.status_code} from {path}")

    # 204, or a 200 with an empty body, means "nothing is happening right now".
    # That is a normal answer, not an error.
    if response.status_code == 204 or not response.content.strip():
        # Cache the empty answer too. Otherwise, with no cricket on, every
        # page click would ask again and burn through the monthly quota.
        _write_cache(cache_name, {})
        return {}

    try:
        data = response.json()
    except ValueError:
        raise CricbuzzError(f"Response from {path} was not valid JSON") from None

    _write_cache(cache_name, data)
    return data


# --------------------------------------------------------------- matches

def get_live_matches() -> dict:
    """Matches in progress. Returns {} when no cricket is being played."""
    return _get("/matches/v1/live", "matches_live", TTL_LIVE)


def get_recent_matches() -> dict:
    """Recently completed matches."""
    return _get("/matches/v1/recent", "matches_recent", TTL_MATCH_LIST)


def get_upcoming_matches() -> dict:
    """Scheduled matches that have not started."""
    return _get("/matches/v1/upcoming", "matches_upcoming", TTL_MATCH_LIST)


def get_scorecard(match_id: int) -> dict:
    """Full scorecard for one match: batting, bowling, partnerships, wickets."""
    return _get(f"/mcenter/v1/{match_id}/hscard",
                f"scorecard_{match_id}", TTL_SCORECARD)


def iter_matches(payload: dict,
                 match_types: set[str] | None = None) -> Iterator[dict]:
    """Yield every matchInfo dict from a /matches/v1/* response.

    All three match-list endpoints share one shape:

        typeMatches[] -> seriesMatches[] -> seriesAdWrapper -> matches[]

    Cricbuzz injects advertising entries into seriesMatches; those have no
    seriesAdWrapper key and are skipped.

    Args:
        payload: the response from get_live/recent/upcoming_matches().
        match_types: optionally restrict to e.g. {"International"}.
    """
    for type_block in payload.get("typeMatches", []):
        match_type = type_block.get("matchType")

        if match_types and match_type not in match_types:
            continue

        for series_block in type_block.get("seriesMatches", []):
            wrapper = series_block.get("seriesAdWrapper")
            if wrapper is None:
                continue

            for match in wrapper.get("matches", []):
                info = match.get("matchInfo")
                if info:
                    yield info


# ----------------------------------------------------------------- stats

def get_stat_types() -> dict:
    """The menu of available statistics: mostRuns, highestScore, etc."""
    return _get("/stats/v1/topstats", "topstats", TTL_REFERENCE)


def records_cache_name(stats_type: str, match_type: int | None = None,
                       year: int | None = None, team: int | None = None) -> str:
    """The disk-cache name for one leaderboard, so a page can check whether
    it is already saved (free) before asking the API (costs one call)."""
    parts = ["records", stats_type]
    for name, value in (("matchType", match_type), ("year", year), ("team", team)):
        if value is not None:
            parts.append(f"{name}{value}")
    return "_".join(parts)


def get_records(stats_type: str, match_type: int | None = None,
                year: int | None = None, team: int | None = None) -> dict:
    """Fetch one statistic from the menu.

    Args:
        stats_type: a 'value' from get_stat_types(), e.g. "mostRuns".
        match_type: 1 = test, 2 = odi, 3 = t20.
        year: restrict to a single year.
        team: restrict to one team's players, by teamId.
    """
    params = {"statsType": stats_type}
    for name, value in (("matchType", match_type), ("year", year),
                        ("team", team)):
        if value is not None:
            params[name] = value

    # The records endpoint needs the category "/0" in its path; without it
    # the API just returns the menu again.
    return _get("/stats/v1/topstats/0",
                records_cache_name(stats_type, match_type, year, team),
                TTL_RECORDS, params=params)