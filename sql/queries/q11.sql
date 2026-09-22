-- id: 11
-- title: Runs across formats
-- question: For players who have played at least 2 formats, show total runs in Test, ODI and T20I, plus overall batting average.
-- params: none

-- The archive holds ODIs only, so no player has 2 formats and this returns
-- 0 rows. That is the correct answer for this data. Delete the HAVING line
-- to see every player's ODI column filled in.
SELECT  p.player_name,
        SUM(b.runs_scored) FILTER (WHERE m.match_format = 'Test') AS test_runs,
        SUM(b.runs_scored) FILTER (WHERE m.match_format = 'ODI')  AS odi_runs,
        SUM(b.runs_scored) FILTER (WHERE m.match_format = 'T20I') AS t20i_runs,
        ROUND(SUM(b.runs_scored)::numeric
              / NULLIF(COUNT(*) FILTER (WHERE NOT b.is_not_out), 0), 2)
                                                                  AS overall_average
FROM    fact_batting b
JOIN    fact_match   m ON m.match_id  = b.match_id
JOIN    dim_player   p ON p.player_id = b.player_id
GROUP BY p.player_id, p.player_name
HAVING  COUNT(DISTINCT m.match_format) >= 2
ORDER BY SUM(b.runs_scored) DESC;
