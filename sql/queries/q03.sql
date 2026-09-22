-- id: 3
-- title: Top 10 ODI run scorers
-- question: List the top 10 highest run scorers in ODI cricket with total runs, batting average and number of centuries.
-- params: none

SELECT  p.player_name,
        p.gender,
        SUM(b.runs_scored)                                        AS total_runs,
        ROUND(SUM(b.runs_scored)::numeric
              / NULLIF(COUNT(*) FILTER (WHERE NOT b.is_not_out), 0), 2)
                                                                  AS batting_average,
        COUNT(*) FILTER (WHERE b.runs_scored >= 100)              AS centuries
FROM    fact_batting b
JOIN    dim_player   p ON p.player_id = b.player_id
JOIN    fact_match   m ON m.match_id  = b.match_id
WHERE   m.match_format = 'ODI'
GROUP BY p.player_id, p.player_name, p.gender
ORDER BY total_runs DESC
LIMIT 10;
