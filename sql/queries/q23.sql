-- id: 23
-- title: Recent form
-- question: Using each player's last 10 innings in each format: average of last 5 vs last 10, strike-rate trend, scores of 50+, consistency (std dev), and a form label.
-- params: none

-- ROW_NUMBER numbers each player's innings newest-first (1 = latest).
-- Only players who have batted within the last year of the archive and
-- have 10 innings are rated, so retired players don't get a "form".
-- Form rules (average of the last 5 innings):
--   Excellent  45+ and at least two 50s in the last 10
--   Good       30+
--   Average    18+
--   Poor       below 18
-- Split by format: ODI and T20I numbers are never mixed in one row,
-- because a good ODI average and a good T20I average are different things.
WITH numbered AS (
    SELECT  b.player_id, m.match_format, b.runs_scored, b.balls_faced, m.match_date,
            ROW_NUMBER() OVER (PARTITION BY b.player_id, m.match_format
                               ORDER BY m.match_date DESC, m.match_id DESC) AS rn
    FROM    fact_batting b
    JOIN    fact_match   m ON m.match_id = b.match_id
),
last10 AS (
    SELECT  player_id,
            match_format,
            MAX(match_date)                                                       AS last_innings,
            COUNT(*)                                                              AS innings,
            AVG(runs_scored) FILTER (WHERE rn <= 5)                               AS avg_last5,
            AVG(runs_scored)                                                      AS avg_last10,
            SUM(runs_scored) FILTER (WHERE rn <= 5) * 100.0
                / NULLIF(SUM(balls_faced) FILTER (WHERE rn <= 5), 0)              AS sr_last5,
            SUM(runs_scored) * 100.0 / NULLIF(SUM(balls_faced), 0)                AS sr_last10,
            COUNT(*) FILTER (WHERE runs_scored >= 50)                             AS fifties,
            STDDEV(runs_scored)                                                   AS std_dev
    FROM    numbered
    WHERE   rn <= 10
    GROUP BY player_id, match_format
)
SELECT  p.player_name,
        p.primary_team,
        l.match_format                          AS format,
        l.last_innings,
        ROUND(l.avg_last5, 1)                   AS avg_last5,
        ROUND(l.avg_last10, 1)                  AS avg_last10,
        ROUND(l.sr_last5, 1)                    AS sr_last5,
        ROUND(l.sr_last10, 1)                   AS sr_last10,
        CASE WHEN l.sr_last5 > l.sr_last10 THEN 'Rising'
             WHEN l.sr_last5 < l.sr_last10 THEN 'Falling'
             ELSE 'Flat' END                    AS sr_trend,
        l.fifties                               AS fifties_last10,
        ROUND(l.std_dev, 1)                     AS consistency_std_dev,
        CASE WHEN l.avg_last5 >= 45 AND l.fifties >= 2 THEN 'Excellent Form'
             WHEN l.avg_last5 >= 30                    THEN 'Good Form'
             WHEN l.avg_last5 >= 18                    THEN 'Average Form'
             ELSE 'Poor Form' END               AS form
FROM    last10     l
JOIN    dim_player p ON p.player_id = l.player_id
WHERE   l.innings = 10
  AND   l.last_innings >= (SELECT MAX(match_date) FROM fact_match) - INTERVAL '1 year'
ORDER BY format, l.avg_last5 DESC;