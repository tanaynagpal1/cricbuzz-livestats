-- ===========================================================================
-- Cricbuzz LiveStats — indexes
--
-- Run AFTER the bulk load:
--   psql "$DATABASE_URL" -f sql/02_indexes.sql
--
-- Why after, not before: an index that exists during a load has to be
-- updated on every one of the ~430,000 inserts. Building it once at the end
-- over finished data is markedly faster and produces a better-packed index.
--
-- A primary key already creates an index, so nothing here repeats one. Each
-- index below exists because a specific query pattern needs it.
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- fact_batting — the largest table, and the one most queries start from
-- ---------------------------------------------------------------------------

-- Career questions: every innings by one player. Without this, "most runs
-- by V Kohli" reads all 147,503 rows.
CREATE INDEX IF NOT EXISTS ix_batting_player   ON fact_batting (player_id);

-- Scorecard questions: every batter in one match.
CREATE INDEX IF NOT EXISTS ix_batting_match    ON fact_batting (match_id);

-- The consecutive-batting-position self-join. It must match on match AND
-- innings AND position: joining on position alone would pair a number three
-- from one match with a number four from another, which is nonsense that
-- returns rows rather than an error.
CREATE INDEX IF NOT EXISTS ix_batting_order
    ON fact_batting (match_id, innings_no, batting_position);

-- Fielding questions: catches and stumpings credited to a player. A partial
-- index, because 47% of rows have no fielder and indexing those wastes
-- space and slows writes for nothing.
CREATE INDEX IF NOT EXISTS ix_batting_fielder
    ON fact_batting (fielder_id) WHERE fielder_id IS NOT NULL;

-- Bowler-versus-batter questions.
CREATE INDEX IF NOT EXISTS ix_batting_dismissed_by
    ON fact_batting (dismissed_by_id) WHERE dismissed_by_id IS NOT NULL;


-- ---------------------------------------------------------------------------
-- fact_bowling
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_bowling_player   ON fact_bowling (player_id);
CREATE INDEX IF NOT EXISTS ix_bowling_match    ON fact_bowling (match_id);
CREATE INDEX IF NOT EXISTS ix_bowling_team     ON fact_bowling (team_id);


-- ---------------------------------------------------------------------------
-- fact_match — four role-playing team keys, each queried separately
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_match_date       ON fact_match (date_key);
CREATE INDEX IF NOT EXISTS ix_match_matchdate  ON fact_match (match_date);
CREATE INDEX IF NOT EXISTS ix_match_venue      ON fact_match (venue_id);
CREATE INDEX IF NOT EXISTS ix_match_series     ON fact_match (series_id);
CREATE INDEX IF NOT EXISTS ix_match_team1      ON fact_match (team1_id);
CREATE INDEX IF NOT EXISTS ix_match_team2      ON fact_match (team2_id);

-- 263 matches have no winner; excluding them keeps the index smaller and
-- matches how it is actually queried — nobody asks for matches nobody won.
CREATE INDEX IF NOT EXISTS ix_match_winner
    ON fact_match (winner_id) WHERE winner_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_match_toss       ON fact_match (toss_winner_id);

-- Almost every query filters on gender. Pairing gender with the date
-- supports the common shape: "men's matches in 2023, most recent first".
CREATE INDEX IF NOT EXISTS ix_match_gender_date
    ON fact_match (gender, match_date DESC);

-- ODI and T20I sit in one table, and most analysis looks at one format at
-- a time: "ODI run scorers", "T20I economy".
CREATE INDEX IF NOT EXISTS ix_match_format_gender
    ON fact_match (match_format, gender);

-- Knockout questions. Only 639 matches have a stage, so a partial index is
-- tiny and answers "performance in finals" without scanning the table.
CREATE INDEX IF NOT EXISTS ix_match_stage
    ON fact_match (event_stage) WHERE event_stage IS NOT NULL;


-- ---------------------------------------------------------------------------
-- fact_innings
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_innings_batting_team ON fact_innings (batting_team_id);
CREATE INDEX IF NOT EXISTS ix_innings_bowling_team ON fact_innings (bowling_team_id);

-- "Highest totals" and "biggest chases" both scan by score, descending.
CREATE INDEX IF NOT EXISTS ix_innings_runs ON fact_innings (runs_total DESC);


-- ---------------------------------------------------------------------------
-- fact_partnership
-- ---------------------------------------------------------------------------
-- Two separate indexes rather than one composite: a partnership is looked
-- up by EITHER batter, and a composite on (batter1, batter2) cannot serve a
-- query that filters only on the second.
CREATE INDEX IF NOT EXISTS ix_partnership_b1   ON fact_partnership (batter1_id);
CREATE INDEX IF NOT EXISTS ix_partnership_b2   ON fact_partnership (batter2_id);
CREATE INDEX IF NOT EXISTS ix_partnership_runs ON fact_partnership (runs DESC);


-- ---------------------------------------------------------------------------
-- dimensions — lookups from the UI
-- ---------------------------------------------------------------------------
-- Player search. lower() so "kohli" matches "V Kohli" without the index
-- being bypassed by the function call in the WHERE clause.
CREATE INDEX IF NOT EXISTS ix_player_name_lower ON dim_player (lower(player_name));
CREATE INDEX IF NOT EXISTS ix_player_role       ON dim_player (playing_role);
CREATE INDEX IF NOT EXISTS ix_player_team       ON dim_player (primary_team);

CREATE INDEX IF NOT EXISTS ix_venue_country     ON dim_venue (country);
CREATE INDEX IF NOT EXISTS ix_venue_home_nation ON dim_venue (home_nation)
    WHERE home_nation IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_series_season     ON dim_series (season_start);
CREATE INDEX IF NOT EXISTS ix_date_year_quarter ON dim_date (year, quarter);

COMMIT;


-- ===========================================================================
-- Statistics
--
-- ANALYZE updates the planner's statistics. Without it, PostgreSQL plans
-- queries against a table it believes is empty, and will happily choose a
-- sequential scan over the index you just built.
-- ===========================================================================
ANALYZE dim_player;
ANALYZE dim_team;
ANALYZE dim_venue;
ANALYZE dim_series;
ANALYZE dim_date;
ANALYZE fact_match;
ANALYZE fact_innings;
ANALYZE fact_batting;
ANALYZE fact_bowling;
ANALYZE fact_partnership;