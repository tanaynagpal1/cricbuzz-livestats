-- id: 19
-- title: Most consistent batters since 2022
-- question: Average runs and standard deviation of runs per batter since 2022, counting only innings of 10+ balls. Lower deviation = more consistent.
-- params: none

-- Two extra rules, both needed for a sensible answer:
--   * 10+ qualifying innings — a deviation over 2 or 3 innings means nothing.
--   * average of 30+ — otherwise tail-enders who ALWAYS score little top the
--     list as the "most consistent batters".
SELECT  p.player_name,
        p.primary_team,
        COUNT(*)                            AS innings,
        ROUND(AVG(b.runs_scored), 2)        AS avg_runs,
        ROUND(STDDEV(b.runs_scored), 2)     AS std_dev_runs
FROM    fact_batting b
JOIN    fact_match   m ON m.match_id  = b.match_id
JOIN    dim_player   p ON p.player_id = b.player_id
WHERE   m.match_date >= DATE '2022-01-01'
  AND   b.balls_faced >= 10
GROUP BY p.player_id, p.player_name, p.primary_team
HAVING  COUNT(*) >= 10
   AND  AVG(b.runs_scored) >= 30
ORDER BY std_dev_runs;
