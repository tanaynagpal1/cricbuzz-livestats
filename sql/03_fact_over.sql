-- ===========================================================================
-- fact_over — one row per over · grain: (match, innings, over)
--
-- Added after the first ten tables, so it lives in its own file and is
-- loaded by its own script (etl/07_load_fact_over.py). Re-running it drops
-- and recreates ONLY this table; the other ten are never touched.
--
-- ~274,000 rows. Feeds the worm, the Manhattan, the chase-pressure chart
-- and bowling by phase.
-- ===========================================================================

BEGIN;

DROP TABLE IF EXISTS fact_over;

CREATE TABLE fact_over (
    match_id         BIGINT      NOT NULL,
    innings_no       SMALLINT    NOT NULL CHECK (innings_no BETWEEN 1 AND 2),
    over_no          SMALLINT    NOT NULL CHECK (over_no >= 1),   -- 1-based, as on a scorecard

    batting_team_id  SMALLINT    NOT NULL REFERENCES dim_team(team_id),
    bowling_team_id  SMALLINT    NOT NULL REFERENCES dim_team(team_id),

    -- The bowler of most deliveries in the over. 163 overs were finished by
    -- a second bowler; bowlers_used records that rather than hiding it.
    bowler_id        VARCHAR(16) NOT NULL REFERENCES dim_player(player_id),
    bowlers_used     SMALLINT    NOT NULL CHECK (bowlers_used >= 1),

    -- Same boundaries as fact_innings' pp_/middle_/death_ columns:
    -- first 10 overs, last 10 overs, and everything between.
    phase            TEXT        NOT NULL CHECK (phase IN ('powerplay', 'middle', 'death')),

    runs             SMALLINT    NOT NULL CHECK (runs >= 0),       -- scoreboard runs
    runs_off_bat     SMALLINT    NOT NULL CHECK (runs_off_bat >= 0),
    extras           SMALLINT    NOT NULL DEFAULT 0,
    wides            SMALLINT    NOT NULL DEFAULT 0,
    noballs          SMALLINT    NOT NULL DEFAULT 0,

    -- NOT capped at 6: an over with a miscount, or cut short by the end of
    -- an innings, is real data.
    legal_balls      SMALLINT    NOT NULL CHECK (legal_balls >= 0),
    dots             SMALLINT    NOT NULL DEFAULT 0,
    fours            SMALLINT    NOT NULL DEFAULT 0,
    sixes            SMALLINT    NOT NULL DEFAULT 0,

    wickets          SMALLINT    NOT NULL DEFAULT 0,   -- all dismissals (not retirements)
    bowler_wickets   SMALLINT    NOT NULL DEFAULT 0,   -- only those credited to the bowler
    bowler_runs      SMALLINT    NOT NULL DEFAULT 0,   -- runs charged to the bowler

    -- Running totals at the END of this over. The worm chart plots these
    -- directly; computing them in every query would repeat the same window.
    cum_runs         SMALLINT    NOT NULL,
    cum_wickets      SMALLINT    NOT NULL CHECK (cum_wickets BETWEEN 0 AND 10),
    cum_legal_balls  SMALLINT    NOT NULL,

    PRIMARY KEY (match_id, innings_no, over_no),
    FOREIGN KEY (match_id, innings_no) REFERENCES fact_innings(match_id, innings_no),
    CONSTRAINT fact_over_runs_add_up CHECK (runs = runs_off_bat + extras),
    CONSTRAINT fact_over_two_teams   CHECK (batting_team_id <> bowling_team_id)
);

COMMENT ON TABLE fact_over IS
    'One row per over. Sums back exactly to fact_innings and fact_bowling.';

COMMIT;