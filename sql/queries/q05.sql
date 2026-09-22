-- id: 5
-- title: Wins by team
-- question: Calculate how many matches each team has won. Show team name and total wins, most wins first.
-- params: none

-- Matches with no result or a tie have no winner (winner_id is NULL),
-- so the JOIN leaves them out automatically.
SELECT  t.team_display   AS team,
        COUNT(*)         AS total_wins
FROM    fact_match m
JOIN    dim_team   t ON t.team_id = m.winner_id
GROUP BY t.team_id, t.team_display
ORDER BY total_wins DESC, team;
