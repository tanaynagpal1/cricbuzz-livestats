"""Download Cricsheet match bundles into data/raw/.

Run from the project root:
    python etl/01_download_cricsheet.py

Existing files are skipped, so re-running is safe and free.
"""

from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

BUNDLES = {
    "odis_json.zip": "https://cricsheet.org/downloads/odis_json.zip",

    # The player register: full names plus cross-reference ids for 12 other
    # sites, including key_cricbuzz. Saves a name-search request per player.
    "people.csv": "https://cricsheet.org/register/people.csv",

    # Uncomment once the ODI pipeline works end to end:
    # "tests_json.zip": "https://cricsheet.org/downloads/tests_json.zip",
"t20s_json.zip": "https://cricsheet.org/downloads/t20s_json.zip",
}


def download(url: str, dest: Path) -> None:
    """Stream a file to disk, skipping it if we already have it."""
    if dest.exists():
        print(f"EXISTS   {dest.name}  ({dest.stat().st_size / 1e6:.1f} MB)")
        return

    print(f"DOWNLOAD {url}")

    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        written = 0

        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)
                written += len(chunk)
                if total:
                    pct = written * 100 / total
                    print(f"\r         {written / 1e6:6.1f} / {total / 1e6:.1f} MB"
                          f"  ({pct:.0f}%)", end="", flush=True)

    print(f"\nSAVED    {dest.name}  ({dest.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"target: {RAW_DIR}\n")

    for filename, url in BUNDLES.items():
        download(url, RAW_DIR / filename)


if __name__ == "__main__":
    main()