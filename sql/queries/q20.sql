-- id: 20
-- title: Matches and averages by format
-- question: For players with 20+ matches, show the number of Test, ODI and T20 matches and the batting average in each.
-- params: none

-- Test and T20 columns are 0 / empty because the archive holds ODIs only.
SELECT  p.player_name,
        COUNT(DISTINCT b.match_id) FILTER (WHERE m.match_format = 'Test')            AS test_matches,
        COUNT(DISTINCT b.match_id) FILTER (WHERE m.match_format = 'ODI')             AS odi_matches,
        COUNT(DISTINCT b.match_id) FILTER (WHERE m.match_format IN ('T20I', 'T20'))  AS t20_matches,
        ROUND(SUM(b.runs_scored) FILTER (WHERE m.match_format = 'Test')::numeric
              / NULLIF(COUNT(*) FILTER (WHERE m.match_format = 'Test' AND NOT b.is_not_out), 0), 2) AS test_avg,
        ROUND(SUM(b.runs_scored) FILTER (WHERE m.match_format = 'ODI')::numeric
              / NULLIF(COUNT(*) FILTER (WHERE m.match_format = 'ODI' AND NOT b.is_not_out), 0), 2)  AS odi_avg,
        ROUND(SUM(b.runs_scored) FILTER (WHERE m.match_format IN ('T20I', 'T20'))::numeric
              / NULLIF(COUNT(*) FILTER (WHERE m.match_format IN ('T20I', 'T20') AND NOT b.is_not_out), 0), 2) AS t20_avg
FROM    fact_batting b
JOIN    fact_match   m ON m.match_id  = b.match_id
JOIN    dim_player   p ON p.player_id = b.player_id
GROUP BY p.player_id, p.player_name
HAVING  COUNT(DISTINCT b.match_id) >= 20
ORDER BY odi_matches DESC;
