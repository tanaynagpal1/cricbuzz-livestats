-- id: 14
-- title: Bowling performance by venue
-- question: For bowlers with at least 3 matches at the same venue (bowling at least 4 overs in each), show average economy, total wickets and matches at that venue.
-- params: none

-- 4 overs = 24 legal balls. Spells shorter than that are removed FIRST
-- (WHERE), then the 3-match rule is applied to what is left (HAVING).
SELECT  p.player_name                                         AS bowler,
        v.venue_name || ', ' || v.city                        AS venue,
        COUNT(DISTINCT w.match_id)                            AS matches,
        ROUND(AVG(w.runs_conceded * 6.0 / w.balls_bowled), 2) AS avg_economy,
        SUM(w.wickets)                                        AS total_wickets
FROM    fact_bowling w
JOIN    fact_match   m ON m.match_id  = w.match_id
JOIN    dim_venue    v ON v.venue_id  = m.venue_id
JOIN    dim_player   p ON p.player_id = w.player_id
WHERE   w.balls_bowled >= 24
GROUP BY p.player_id, p.player_name, v.venue_id, v.venue_name, v.city
HAVING  COUNT(DISTINCT w.match_id) >= 3
ORDER BY total_wickets DESC, avg_economy;
