-- id: 16
-- title: Batting by year since 2020
-- question: For matches since 2020, show each player's average runs per match and average strike rate per year and format, for players with 5+ matches that year.
-- params: none

-- Split by format: ODI and T20I numbers are never mixed in one row,
-- because a good ODI average and a good T20I average are different things.
SELECT  p.player_name,
        m.match_format                                                    AS format,
        d.year,
        COUNT(DISTINCT b.match_id)                                        AS matches,
        ROUND(AVG(b.runs_scored), 2)                                      AS avg_runs,
        ROUND(AVG(b.runs_scored * 100.0 / NULLIF(b.balls_faced, 0)), 2)   AS avg_strike_rate
FROM    fact_batting b
JOIN    fact_match   m ON m.match_id  = b.match_id
JOIN    dim_date     d ON d.date_key  = m.date_key
JOIN    dim_player   p ON p.player_id = b.player_id
WHERE   d.year >= 2020
GROUP BY p.player_id, p.player_name, m.match_format, d.year
HAVING  COUNT(DISTINCT b.match_id) >= 5
ORDER BY p.player_name, format, d.year;