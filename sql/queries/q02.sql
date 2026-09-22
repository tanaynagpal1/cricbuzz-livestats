-- id: 2
-- title: Matches in the last 30 days
-- question: Show all matches played in the last 30 days with description, both teams, venue with city and date. Most recent first.
-- params: none

-- "Last 30 days" counts back from the latest match in the archive, not from
-- today, so the answer does not change depending on the day it is run.
SELECT  t1.team_display || ' vs ' || t2.team_display
            || ', ' || s.series_name        AS match_description,
        t1.team_display                     AS team_1,
        t2.team_display                     AS team_2,
        v.venue_name || ', ' || v.city      AS venue,
        m.match_date
FROM    fact_match  m
JOIN    dim_team    t1 ON t1.team_id  = m.team1_id
JOIN    dim_team    t2 ON t2.team_id  = m.team2_id
JOIN    dim_venue   v  ON v.venue_id  = m.venue_id
JOIN    dim_series  s  ON s.series_id = m.series_id
WHERE   m.match_date >= (SELECT MAX(match_date) FROM fact_match) - 30
ORDER BY m.match_date DESC;
