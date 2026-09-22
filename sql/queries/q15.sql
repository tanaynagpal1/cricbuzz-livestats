-- id: 15
-- title: Performance in close matches
-- question: In close matches (won by under 50 runs or under 5 wickets), show each player's average runs, close matches played and close matches won by their team.
-- params: none

-- Only players with 10+ close-match innings are listed, so one lucky knock
-- doesn't top the table.
WITH close_matches AS (
    SELECT  match_id, winner_id
    FROM    fact_match
    WHERE   (victory_type = 'runs'    AND victory_margin < 50)
       OR   (victory_type = 'wickets' AND victory_margin < 5)
)
SELECT  p.player_name,
        p.primary_team,
        COUNT(DISTINCT b.match_id)                                     AS close_matches,
        ROUND(AVG(b.runs_scored), 2)                                   AS avg_runs,
        COUNT(DISTINCT b.match_id) FILTER (WHERE b.team_id = c.winner_id) AS close_matches_won
FROM    fact_batting  b
JOIN    close_matches c ON c.match_id  = b.match_id
JOIN    dim_player    p ON p.player_id = b.player_id
GROUP BY p.player_id, p.player_name, p.primary_team
HAVING  COUNT(DISTINCT b.match_id) >= 10
ORDER BY avg_runs DESC;
