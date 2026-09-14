"""Verify that local configuration is wired up correctly.

Run this after editing .env. Costs exactly one API request.
"""

import os

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


def check_api_key() -> bool:
    """Call one endpoint and report whether the key was accepted."""
    key = os.getenv("RAPIDAPI_KEY")
    host = os.getenv("RAPIDAPI_HOST")

    if not key:
        print("FAIL  RAPIDAPI_KEY is missing from .env")
        return False
    if not host:
        print("FAIL  RAPIDAPI_HOST is missing from .env")
        return False

    print(f"      key loaded: {len(key)} chars, ending '...{key[-4:]}'")

    url = f"https://{host}/matches/v1/recent"
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as exc:
        print(f"FAIL  could not reach the API: {exc}")
        return False

    print(f"      HTTP {response.status_code}")

    if response.status_code == 200:
        print("PASS  API key accepted")
        return True
    if response.status_code in (401, 403):
        print("FAIL  key rejected or not subscribed")
        return False
    if response.status_code == 429:
        print("FAIL  rate limited or quota exhausted")
        return False

    print(f"WARN  unexpected status {response.status_code}")
    return False


def check_database() -> bool:
    """Connect to PostgreSQL and run a trivial query."""
    url = os.getenv("DATABASE_URL")

    if not url:
        print("FAIL  DATABASE_URL is missing from .env")
        return False

    try:
        host = url.split("@")[1].split("/")[0]
    except IndexError:
        print("FAIL  DATABASE_URL is not a valid connection string")
        return False

    print(f"      host: {host}")
    print("      connecting (first call may take ~5s while Neon wakes up)...")

    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            database = conn.execute(text("SELECT current_database()")).scalar()
            version = conn.execute(text("SELECT version()")).scalar()
    except Exception as exc:
        print(f"FAIL  {type(exc).__name__}: {str(exc)[:200]}")
        return False

    print(f"      database: {database}")
    print(f"      server:   {version.split(',')[0]}")
    print("PASS  connected and ran a query")
    return True


if __name__ == "__main__":
    print("Checking setup...\n")

    print("[1/2] RapidAPI")
    api_ok = check_api_key()

    print("\n[2/2] PostgreSQL")
    db_ok = check_database()

    print("\nSETUP OK" if api_ok and db_ok else "\nSETUP INCOMPLETE")