-- id: 9
-- title: All-rounders with 1000 runs and 50 wickets
-- question: Find all-rounders with more than 1000 runs AND more than 50 wickets. Show player name, total runs, total wickets and format.
-- params: none

-- Runs and wickets are added up in two SEPARATE steps (the two CTEs) and
-- only then joined. Joining batting and bowling rows first and summing
-- afterwards would multiply every total — a classic SQL trap.
WITH runs AS (
    SELECT  b.player_id, m.match_format, SUM(b.runs_scored) AS total_runs
    FROM    fact_batting b
    JOIN    fact_match   m ON m.match_id = b.match_id
    GROUP BY b.player_id, m.match_format
),
wickets AS (
    SELECT  w.player_id, m.match_format, SUM(w.wickets) AS total_wickets
    FROM    fact_bowling w
    JOIN    fact_match   m ON m.match_id = w.match_id
    GROUP BY w.player_id, m.match_format
)
SELECT  p.player_name,
        p.primary_team,
        r.total_runs,
        w.total_wickets,
        r.match_format AS format
FROM    runs       r
JOIN    wickets    w ON w.player_id    = r.player_id
                    AND w.match_format = r.match_format
JOIN    dim_player p ON p.player_id    = r.player_id
WHERE   p.playing_role = 'All-rounder'
  AND   r.total_runs    > 1000
  AND   w.total_wickets > 50
ORDER BY r.total_runs DESC;
