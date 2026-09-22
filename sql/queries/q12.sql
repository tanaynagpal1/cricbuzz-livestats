-- id: 12
-- title: Home vs away wins
-- question: For each team, count wins at home and away, where home means the venue's country matches the team's country.
-- params: none

-- Step 1 turns each match into TWO rows, one per team, so every team can
-- be judged on its own. Step 2 labels the venue from that team's point of
-- view: its own ground = Home, the opponent's ground = Away, anywhere
-- else = Neutral. home_nation is used rather than country so that West
-- Indies are at home in Jamaica, Barbados and Trinidad.
WITH team_match AS (
    SELECT match_id, team1_id AS team_id, team2_id AS opponent_id, venue_id, winner_id FROM fact_match
    UNION ALL
    SELECT match_id, team2_id,            team1_id,                venue_id, winner_id FROM fact_match
),
labelled AS (
    SELECT  t.team_display,
            CASE WHEN v.home_nation = t.team_name THEN 'Home'
                 WHEN v.home_nation = o.team_name THEN 'Away'
                 ELSE 'Neutral' END                     AS venue_type,
            (tm.winner_id = tm.team_id)                 AS won
    FROM    team_match tm
    JOIN    dim_team  t ON t.team_id  = tm.team_id
    JOIN    dim_team  o ON o.team_id  = tm.opponent_id
    JOIN    dim_venue v ON v.venue_id = tm.venue_id
)
SELECT  team_display                                                AS team,
        COUNT(*) FILTER (WHERE venue_type = 'Home')                 AS home_matches,
        COUNT(*) FILTER (WHERE venue_type = 'Home' AND won)         AS home_wins,
        COUNT(*) FILTER (WHERE venue_type = 'Away')                 AS away_matches,
        COUNT(*) FILTER (WHERE venue_type = 'Away' AND won)         AS away_wins,
        COUNT(*) FILTER (WHERE venue_type = 'Neutral')              AS neutral_matches,
        COUNT(*) FILTER (WHERE venue_type = 'Neutral' AND won)      AS neutral_wins
FROM    labelled
GROUP BY team_display
ORDER BY COUNT(*) FILTER (WHERE won) DESC, team;
