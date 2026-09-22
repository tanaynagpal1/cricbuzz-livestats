-- id: 18
-- title: Most economical bowlers
-- question: Most economical bowlers in limited-overs cricket (ODI and T20): overall economy and total wickets, for bowlers with 10+ matches averaging 2+ overs per match.
-- params: none

-- Economy is total runs ÷ total overs, not the average of each match's
-- economy — a 1-over spell must not count as much as a 10-over one.
SELECT  p.player_name                                                  AS bowler,
        p.primary_team,
        COUNT(DISTINCT w.match_id)                                     AS matches,
        ROUND(SUM(w.balls_bowled) / 6.0, 1)                            AS overs,
        ROUND(SUM(w.runs_conceded) * 6.0 / NULLIF(SUM(w.balls_bowled), 0), 2) AS economy,
        SUM(w.wickets)                                                 AS total_wickets
FROM    fact_bowling w
JOIN    fact_match   m ON m.match_id  = w.match_id
JOIN    dim_player   p ON p.player_id = w.player_id
WHERE   m.match_format IN ('ODI', 'T20I', 'T20')
GROUP BY p.player_id, p.player_name, p.primary_team
HAVING  COUNT(DISTINCT w.match_id) >= 10
   AND  SUM(w.balls_bowled) / 6.0 / COUNT(DISTINCT w.match_id) >= 2
ORDER BY economy, total_wickets DESC;
