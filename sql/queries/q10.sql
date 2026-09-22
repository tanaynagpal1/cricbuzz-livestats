-- id: 10
-- title: Last 20 completed matches
-- question: Details of the last 20 completed matches: description, both teams, winner, victory margin, victory type and venue. Most recent first.
-- params: none

-- "Completed" = the match produced a winner. No-results and ties are skipped.
SELECT  t1.team_display || ' vs ' || t2.team_display
            || ', ' || s.series_name                AS match_description,
        t1.team_display                             AS team_1,
        t2.team_display                             AS team_2,
        w.team_display                              AS winner,
        m.victory_margin,
        m.victory_type,
        v.venue_name || ', ' || v.city              AS venue,
        m.match_date
FROM    fact_match m
JOIN    dim_team   t1 ON t1.team_id  = m.team1_id
JOIN    dim_team   t2 ON t2.team_id  = m.team2_id
JOIN    dim_team   w  ON w.team_id   = m.winner_id
JOIN    dim_venue  v  ON v.venue_id  = m.venue_id
JOIN    dim_series s  ON s.series_id = m.series_id
WHERE   m.winner_id IS NOT NULL
ORDER BY m.match_date DESC, m.match_id DESC
LIMIT 20;
