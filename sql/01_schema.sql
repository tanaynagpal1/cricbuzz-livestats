-- ===========================================================================
-- Cricbuzz LiveStats — warehouse schema
-- PostgreSQL 15+   (developed against Neon PostgreSQL 18.6)
--
-- Ten tables: five dimensions, five facts. A constellation schema — several
-- fact tables at different grains sharing one set of conformed dimensions.
-- Holds one-day internationals AND T20 internationals (fact_match.match_format).
-- An eleventh table, fact_over, is added by sql/03_fact_over.sql.
--
-- Run:  psql "$DATABASE_URL" -f sql/01_schema.sql
--
-- Indexes are deliberately NOT here. They go in sql/02_indexes.sql and are
-- applied AFTER the bulk load: an index built first has to be maintained on
-- every one of the 430,000 inserts.
--
-- Two conventions used throughout:
--   * NOT NULL is applied only where the data has been PROVED to have no
--     blanks. A nullable column is a statement that the blank means
--     something — a not-out batter has no dismissal, a neutral venue has no
--     home side.
--   * CHECK constraints are applied only where real data cannot break them.
--     A constraint that rejects true data is worse than no constraint.
-- ===========================================================================

BEGIN;

DROP TABLE IF EXISTS fact_partnership CASCADE;
DROP TABLE IF EXISTS fact_bowling     CASCADE;
DROP TABLE IF EXISTS fact_batting     CASCADE;
DROP TABLE IF EXISTS fact_innings     CASCADE;
DROP TABLE IF EXISTS fact_match       CASCADE;
DROP TABLE IF EXISTS dim_date         CASCADE;
DROP TABLE IF EXISTS dim_series       CASCADE;
DROP TABLE IF EXISTS dim_venue        CASCADE;
DROP TABLE IF EXISTS dim_team         CASCADE;
DROP TABLE IF EXISTS dim_player       CASCADE;


-- ===========================================================================
-- DIMENSIONS
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- dim_player — 8,138 rows
--
-- Keyed on Cricsheet's own player id, which is stable across the archive.
-- Inventing a surrogate would add a lookup and buy nothing.
--
-- Population is every player the FACTS refer to, not everyone on a team
-- sheet: 17 substitute fielders took catches without being selected.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_player (
    player_id          VARCHAR(16)  PRIMARY KEY,
    player_name        TEXT         NOT NULL,
    gender             TEXT         NOT NULL CHECK (gender IN ('male', 'female')),
    primary_team       TEXT,
    teams_played_for   SMALLINT     CHECK (teams_played_for >= 0),
    debut              DATE,
    last_match         DATE,

    -- playing_role is DERIVED from behaviour, not declared by anyone. The
    -- three inputs are stored beside it so the classification can be
    -- audited rather than trusted — the same principle as
    -- dim_venue.capacity_source.
    playing_role       TEXT         NOT NULL,
    bowl_share         NUMERIC(6,4),
    avg_position       NUMERIC(5,2),
    dismissal_rate     NUMERIC(6,4),

    -- Not available from any free ball-by-ball source. NULL rather than
    -- guessed. Backfilled on Day 12 from Wikidata via the cricinfo id.
    batting_style      TEXT,
    bowling_style      TEXT,

    CONSTRAINT dim_player_dates CHECK (last_match IS NULL
                                       OR debut IS NULL
                                       OR last_match >= debut)
);

COMMENT ON TABLE  dim_player IS 'One row per cricketer referenced anywhere in the facts.';
COMMENT ON COLUMN dim_player.playing_role IS
    'Derived: bowling share, average batting position, and catches plus '
    'stumpings per match. Not an official designation.';


-- ---------------------------------------------------------------------------
-- dim_team — 200 rows
--
-- The natural key is (team_name, gender), not the name. "England" is two
-- different international sides; merging them blends two competitions in
-- every head-to-head and home-advantage answer. Thailand shows the same
-- point from the other direction: 17 women's matches, no men's side at all.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_team (
    team_id       SMALLINT  PRIMARY KEY,
    team_name     TEXT      NOT NULL,
    gender        TEXT      NOT NULL CHECK (gender IN ('male', 'female')),
    team_display  TEXT      NOT NULL,

    CONSTRAINT dim_team_natural_key UNIQUE (team_name, gender)
);

COMMENT ON TABLE dim_team IS
    'One row per national side per gender. 16 countries field both.';


-- ---------------------------------------------------------------------------
-- dim_venue — 367 rows
--
-- The natural key is (venue_name, city). "County Ground" is seven different
-- grounds in seven English cities; the name alone is not an identity.
--
-- country and home_nation are two different facts and get two columns:
-- Sabina Park IS in Jamaica, and the side that PLAYS there is West Indies.
-- Forcing both into one column made the home-advantage query choose between
-- honest geography and a working join.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_venue (
    venue_id         SMALLINT  PRIMARY KEY,
    venue_name       TEXT      NOT NULL,
    venue_display    TEXT      NOT NULL,
    former_names     TEXT,
    city             TEXT      NOT NULL,
    country          TEXT      NOT NULL,

    -- NULL where a country hosts cricket but fields no international side
    -- (Colombia, New Caledonia). A blank is honest; a string that looks
    -- joinable and never joins is worse than nothing.
    home_nation      TEXT,

    -- 196 of 367. Current capacity as of Sept 2026, not capacity on the day
    -- of the match. The rest are mostly club grounds with no published
    -- figure and are left blank rather than estimated.
    capacity         INTEGER   CHECK (capacity IS NULL
                                      OR (capacity > 0 AND capacity <= 150000)),
    capacity_source  TEXT,

    CONSTRAINT dim_venue_natural_key UNIQUE (venue_name, city)
);

COMMENT ON COLUMN dim_venue.country     IS 'Where the ground physically is.';
COMMENT ON COLUMN dim_venue.home_nation IS 'Which international side calls it home.';


-- ---------------------------------------------------------------------------
-- dim_series — 1,497 rows
--
-- Grain is one EDITION: (series_name, season, gender). The 2011 and 2023
-- World Cups are separate rows, so "who won most World Cup matches" and
-- "how did India do in 2011" are both answerable.
--
-- series_id = 0 is the Unknown member, used by the 80 one-off fixtures that
-- belong to no series. They point at it rather than carrying NULL, because
-- an INNER JOIN to a NULL key drops those rows SILENTLY — no error, just
-- 8,831 rows where there should be 8,911.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_series (
    series_id     SMALLINT  PRIMARY KEY,
    series_name   TEXT      NOT NULL,

    -- TEXT, not a number: "2010/11" is a label for a season that spans two
    -- calendar years. season_start carries the sortable form.
    season        TEXT,
    gender        TEXT      CHECK (gender IS NULL OR gender IN ('male', 'female')),
    season_start  SMALLINT,
    first_match   DATE,
    last_match    DATE
);

COMMENT ON TABLE dim_series IS
    'One row per tournament edition. series_id = 0 is the Unknown member.';


-- ---------------------------------------------------------------------------
-- dim_date — 8,849 rows
--
-- One row per CALENDAR DAY across the whole range, not one per day that had
-- a match. That is what lets a quarterly chart show a quarter with zero
-- matches instead of skipping it.
-- ---------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key    INTEGER   PRIMARY KEY,          -- YYYYMMDD
    full_date   DATE      NOT NULL UNIQUE,
    year        SMALLINT  NOT NULL,
    quarter     SMALLINT  NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month       SMALLINT  NOT NULL CHECK (month   BETWEEN 1 AND 12),
    month_name  TEXT      NOT NULL,
    day         SMALLINT  NOT NULL CHECK (day     BETWEEN 1 AND 31),
    day_name    TEXT      NOT NULL,
    is_weekend  BOOLEAN   NOT NULL
);


-- ===========================================================================
-- FACTS
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- fact_match — 8,911 rows · grain: one match
--
-- match_id is Cricsheet's own id, used directly as the primary key — a
-- degenerate dimension.
--
-- FOUR foreign keys point at dim_team from one row. That is a ROLE-PLAYING
-- dimension: each join needs its own alias, which is what makes the
-- home-advantage question a real exercise rather than a lookup.
--
-- winner_id is nullable because 263 matches had no winner — no result, tie,
-- or abandoned. Those must leave the denominator of any toss-advantage
-- calculation.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_match (
    match_id            BIGINT    PRIMARY KEY,

    date_key            INTEGER   NOT NULL REFERENCES dim_date(date_key),
    match_date          DATE      NOT NULL,
    venue_id            SMALLINT  NOT NULL REFERENCES dim_venue(venue_id),
    series_id           SMALLINT  NOT NULL REFERENCES dim_series(series_id),

    team1_id            SMALLINT  NOT NULL REFERENCES dim_team(team_id),
    team2_id            SMALLINT  NOT NULL REFERENCES dim_team(team_id),
    toss_winner_id      SMALLINT  REFERENCES dim_team(team_id),
    winner_id           SMALLINT  REFERENCES dim_team(team_id),
    player_of_match_id  VARCHAR(16) REFERENCES dim_player(player_id),

    toss_decision       TEXT      CHECK (toss_decision IS NULL
                                         OR toss_decision IN ('bat', 'field')),
    victory_type        TEXT,
    victory_margin      SMALLINT  CHECK (victory_margin IS NULL
                                         OR victory_margin >= 0),
    victory_method      TEXT,

    gender              TEXT      NOT NULL CHECK (gender IN ('male', 'female')),
    match_format        TEXT      NOT NULL,
    match_type_number   INTEGER,
    season              TEXT,
    scheduled_overs     SMALLINT,
    balls_per_over      SMALLINT,

    event_stage         TEXT,
    event_group         TEXT,
    event_match_number  INTEGER,

    CONSTRAINT fact_match_two_teams CHECK (team1_id <> team2_id)
);

COMMENT ON COLUMN fact_match.winner_id IS
    'NULL on 263 matches with no result, a tie, or abandonment.';


-- ---------------------------------------------------------------------------
-- fact_innings — 17,657 rows · grain: one team's innings in one match
--
-- This table exists because NEITHER player-level table can produce a team's
-- score. fact_batting holds only runs off the bat; fact_bowling includes
-- wides and no-balls but excludes byes and leg-byes, which are not the
-- bowler's fault. England's world-record 498 reads as 476 in one and 492 in
-- the other. Summing every delivery's total gives 498.
--
-- runs_total = runs_off_bat + extras_total is enforced by the ETL on all
-- 17,657 rows, and checked here as well.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_innings (
    match_id         BIGINT    NOT NULL REFERENCES fact_match(match_id),
    innings_no       SMALLINT  NOT NULL CHECK (innings_no BETWEEN 1 AND 2),
    batting_team_id  SMALLINT  NOT NULL REFERENCES dim_team(team_id),
    bowling_team_id  SMALLINT  NOT NULL REFERENCES dim_team(team_id),

    runs_total       SMALLINT  NOT NULL CHECK (runs_total   >= 0),
    wickets_lost     SMALLINT  NOT NULL CHECK (wickets_lost BETWEEN 0 AND 10),
    legal_balls      SMALLINT  NOT NULL CHECK (legal_balls  >= 0),
    runs_off_bat     SMALLINT  NOT NULL CHECK (runs_off_bat >= 0),

    extras_total     SMALLINT  NOT NULL DEFAULT 0,
    extras_wides     SMALLINT  NOT NULL DEFAULT 0,
    extras_noballs   SMALLINT  NOT NULL DEFAULT 0,
    extras_byes      SMALLINT  NOT NULL DEFAULT 0,
    extras_legbyes   SMALLINT  NOT NULL DEFAULT 0,
    extras_penalty   SMALLINT  NOT NULL DEFAULT 0,

    fours            SMALLINT  NOT NULL DEFAULT 0,
    sixes            SMALLINT  NOT NULL DEFAULT 0,
    dots             SMALLINT  NOT NULL DEFAULT 0,

    -- Present only on an innings batting second, and only where a revised
    -- target was set.
    target_runs      SMALLINT,
    target_overs     NUMERIC(5,1),

    penalty_runs     SMALLINT  NOT NULL DEFAULT 0,
    absent_hurt      SMALLINT  NOT NULL DEFAULT 0,
    overs_recorded   SMALLINT,

    -- Phase splits: ODI = first 10 and last 10 overs; T20I = first 6 and
    -- last 5. Fixed counts, because the JSON's own powerplay blocks shift
    -- between eras and get rewritten when rain cuts an innings short.
    pp_runs          SMALLINT  NOT NULL DEFAULT 0,
    pp_balls         SMALLINT  NOT NULL DEFAULT 0,
    pp_wickets       SMALLINT  NOT NULL DEFAULT 0,
    middle_runs      SMALLINT  NOT NULL DEFAULT 0,
    middle_balls     SMALLINT  NOT NULL DEFAULT 0,
    middle_wickets   SMALLINT  NOT NULL DEFAULT 0,
    death_runs       SMALLINT  NOT NULL DEFAULT 0,
    death_balls      SMALLINT  NOT NULL DEFAULT 0,
    death_wickets    SMALLINT  NOT NULL DEFAULT 0,

    PRIMARY KEY (match_id, innings_no),
    CONSTRAINT fact_innings_two_teams CHECK (batting_team_id <> bowling_team_id),
    CONSTRAINT fact_innings_reconciles CHECK (runs_total = runs_off_bat + extras_total),
    CONSTRAINT fact_innings_phases     CHECK (runs_total = pp_runs + middle_runs + death_runs)
);


-- ---------------------------------------------------------------------------
-- fact_batting — 147,503 rows · grain: one player's innings
--
-- The primary key was proved unique before being declared: a player bats
-- once per innings.
--
-- batting_position reaches 12 — concussion substitutes — so it is NOT
-- constrained to 11.
--
-- The three nullable columns each mean something specific: a not-out batter
-- has no dismissal_kind, a run-out batter has no dismissed_by_id (the
-- bowler gets no credit), and a bowled batter has no fielder_id.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_batting (
    match_id          BIGINT      NOT NULL REFERENCES fact_match(match_id),
    innings_no        SMALLINT    NOT NULL CHECK (innings_no BETWEEN 1 AND 2),
    player_id         VARCHAR(16) NOT NULL REFERENCES dim_player(player_id),
    team_id           SMALLINT    NOT NULL REFERENCES dim_team(team_id),

    batting_position  SMALLINT    NOT NULL CHECK (batting_position >= 1),
    runs_scored       SMALLINT    NOT NULL CHECK (runs_scored >= 0),
    balls_faced       SMALLINT    NOT NULL CHECK (balls_faced >= 0),
    fours             SMALLINT    NOT NULL DEFAULT 0,
    sixes             SMALLINT    NOT NULL DEFAULT 0,
    is_not_out        BOOLEAN     NOT NULL,

    dismissal_kind    TEXT,
    dismissed_by_id   VARCHAR(16) REFERENCES dim_player(player_id),
    fielder_id        VARCHAR(16) REFERENCES dim_player(player_id),

    PRIMARY KEY (match_id, innings_no, player_id),

    -- Either the batter was out and we know how, or they were not out and
    -- there is nothing to record. Anything else is a parsing bug.
    CONSTRAINT fact_batting_dismissal CHECK (
        (is_not_out AND dismissal_kind IS NULL)
        OR (NOT is_not_out AND dismissal_kind IS NOT NULL)
    )
);

COMMENT ON COLUMN fact_batting.dismissed_by_id IS
    'NULL for run outs — the bowler is credited with the wicket only for '
    'bowled, caught, lbw, stumped, caught and bowled, and hit wicket.';


-- ---------------------------------------------------------------------------
-- fact_bowling — 106,534 rows · grain: one bowler's spell in one innings
--
-- There is deliberately NO check that balls_bowled <= 60. Sixteen spells
-- run to 61 because an umpire miscounted an over, and one records 11 overs
-- (a source error, carried unchanged rather than replaced by a number we
-- would have invented). A constraint that rejects true data is worse than
-- no constraint.
--
-- balls_bowled CAN be 0 — two bowlers conceded runs off nothing but wides —
-- so economy must be computed as NULL, never as a division.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_bowling (
    match_id       BIGINT      NOT NULL REFERENCES fact_match(match_id),
    innings_no     SMALLINT    NOT NULL CHECK (innings_no BETWEEN 1 AND 2),
    player_id      VARCHAR(16) NOT NULL REFERENCES dim_player(player_id),
    team_id        SMALLINT    NOT NULL REFERENCES dim_team(team_id),

    balls_bowled   SMALLINT    NOT NULL CHECK (balls_bowled  >= 0),
    runs_conceded  SMALLINT    NOT NULL CHECK (runs_conceded >= 0),
    wickets        SMALLINT    NOT NULL CHECK (wickets BETWEEN 0 AND 10),
    maidens        SMALLINT    NOT NULL DEFAULT 0,
    dots           SMALLINT    NOT NULL DEFAULT 0,

    PRIMARY KEY (match_id, innings_no, player_id)
);


-- ---------------------------------------------------------------------------
-- fact_partnership — 129,941 rows · grain: one partnership
--
-- Runs include extras, which is how partnerships are scored in cricket.
-- Balls exclude wides, which are not faced.
--
-- wicket_no is NOT constrained to 10. A batter who retires hurt and returns
-- creates an extra stand without a wicket falling, so the sequence can run
-- past ten.
-- ---------------------------------------------------------------------------
CREATE TABLE fact_partnership (
    match_id         BIGINT      NOT NULL REFERENCES fact_match(match_id),
    innings_no       SMALLINT    NOT NULL CHECK (innings_no BETWEEN 1 AND 2),
    wicket_no        SMALLINT    NOT NULL CHECK (wicket_no >= 1),
    batting_team_id  SMALLINT    NOT NULL REFERENCES dim_team(team_id),

    batter1_id       VARCHAR(16) NOT NULL REFERENCES dim_player(player_id),
    batter2_id       VARCHAR(16) NOT NULL REFERENCES dim_player(player_id),

    runs             SMALLINT    NOT NULL CHECK (runs  >= 0),
    balls            SMALLINT    NOT NULL CHECK (balls >= 0),
    unbroken         BOOLEAN     NOT NULL,

    PRIMARY KEY (match_id, innings_no, wicket_no),
    CONSTRAINT fact_partnership_two_batters CHECK (batter1_id <> batter2_id),
    FOREIGN KEY (match_id, innings_no) REFERENCES fact_innings(match_id, innings_no)
);

COMMENT ON TABLE fact_partnership IS
    'One row per stand. Runs include extras; balls exclude wides.';


COMMIT;

-- ===========================================================================
-- Note on deletes
--
-- Every foreign key uses the default ON DELETE RESTRICT. Deleting a player
-- who has batting records therefore FAILS rather than cascading. That is
-- deliberate: the CRUD page must show a handled error and leave the
-- database unchanged, which is exactly what the brief asks for.
-- ===========================================================================