# Cricbuzz LiveStats

Real-time cricket analytics dashboard — live match data from the Cricbuzz API
combined with ~20 years of historical performance data in PostgreSQL, surfaced
through a multi-page Streamlit application.

**Status:** in development

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| Database | PostgreSQL 18 (Neon, serverless) |
| Web UI | Streamlit |
| Live data | Cricbuzz Cricket API via RapidAPI |
| Historical data | Cricsheet ball-by-ball JSON |

## Architecture

Two independent data paths:

- **Hot path** — Cricbuzz REST API, read-through with caching, never persisted.
  Powers the live and upcoming match pages.
- **Cold path** — Cricsheet JSON, ETL'd into a dimensional model in PostgreSQL.
  Powers SQL analytics and CRUD.

Four of the five pages never touch the API, so the dashboard still works when
the API is unavailable or the free-tier quota is spent.

## Setup

1. Clone the repository
2. Create and activate a virtual environment
py -m venv .venv
..venv\Scripts\Activate.ps1

3. Install dependencies
python -m pip install -r requirements.txt

4. Copy `.env.example` to `.env` and fill in your own credentials:
   - `RAPIDAPI_KEY` — from rapidapi.com, subscribe to Cricbuzz Cricket (Basic plan)
   - `DATABASE_URL` — PostgreSQL connection string
5. Verify the setup


## Project structure
pages/ Streamlit pages (Home, Live, Top Stats, SQL Analytics, CRUD)
utils/ Database connection, API client, shared helpers
etl/ One-time pipeline: download, parse, load
sql/ Schema DDL and the 25 analytics queries
notebooks/ Exploration
data/ Raw and processed data (gitignored)


## Data sources

- Live and upcoming matches: [Cricbuzz Cricket API](https://rapidapi.com/cricketapilive/api/cricbuzz-cricket) via RapidAPI
- Historical match data: [Cricsheet](https://cricsheet.org) — ball-by-ball JSON