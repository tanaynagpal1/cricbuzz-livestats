-- id: 25
-- title: Career trajectory by quarter
-- question: Track each player's quarterly runs and strike rate, compare each quarter with the previous one, and label the career phase (Ascending, Declining, Stable). Players with 6+ quarters of 3+ matches only.
-- params: none

-- Step 1  quarterly: one row per player per quarter (3+ matches only).
-- Step 2  compared: LAG() fetches the previous quarter so each quarter can
--         be labelled Improving / Declining / Stable (±10% on average runs).
-- Step 3  per player: count the labels and compare the first 3 quarters
--         with the last 3. Last 3 more than 10% higher = Career Ascending,
--         more than 10% lower = Career Declining, otherwise Career Stable.
WITH quarterly AS (
    SELECT  b.player_id,
            d.year,
            d.quarter,
            d.year || '-Q' || d.quarter                                  AS period,
            COUNT(DISTINCT b.match_id)                                   AS matches,
            AVG(b.runs_scored)                                           AS avg_runs,
            SUM(b.runs_scored) * 100.0 / NULLIF(SUM(b.balls_faced), 0)   AS strike_rate
    FROM    fact_batting b
    JOIN    fact_match   m ON m.match_id = b.match_id
    JOIN    dim_date     d ON d.date_key = m.date_key
    GROUP BY b.player_id, d.year, d.quarter
    HAVING  COUNT(DISTINCT b.match_id) >= 3
),
compared AS (
    SELECT  q.*,
            LAG(avg_runs) OVER w                                         AS prev_avg,
            ROW_NUMBER()  OVER w                                         AS q_first,
            ROW_NUMBER()  OVER (PARTITION BY player_id
                                ORDER BY year DESC, quarter DESC)        AS q_last,
            COUNT(*)      OVER (PARTITION BY player_id)                  AS quarters
    FROM    quarterly q
    WINDOW  w AS (PARTITION BY player_id ORDER BY year, quarter)
),
summary AS (
    SELECT  player_id,
            MAX(quarters)                                                AS quarters,
            MIN(period)                                                  AS first_quarter,
            MAX(period)                                                  AS last_quarter,
            COUNT(*) FILTER (WHERE avg_runs > prev_avg * 1.1)            AS improving_q,
            COUNT(*) FILTER (WHERE avg_runs < prev_avg * 0.9)            AS declining_q,
            COUNT(*) FILTER (WHERE prev_avg IS NOT NULL
                             AND avg_runs BETWEEN prev_avg * 0.9 AND prev_avg * 1.1) AS stable_q,
            AVG(avg_runs)    FILTER (WHERE q_first <= 3)                 AS early_avg,
            AVG(avg_runs)    FILTER (WHERE q_last  <= 3)                 AS recent_avg,
            AVG(strike_rate) FILTER (WHERE q_first <= 3)                 AS early_sr,
            AVG(strike_rate) FILTER (WHERE q_last  <= 3)                 AS recent_sr
    FROM    compared
    GROUP BY player_id
    HAVING  MAX(quarters) >= 6
)
SELECT  p.player_name,
        p.primary_team,
        s.quarters,
        s.first_quarter,
        s.last_quarter,
        ROUND(s.early_avg, 1)       AS early_avg_runs,
        ROUND(s.recent_avg, 1)      AS recent_avg_runs,
        ROUND(s.early_sr, 1)        AS early_strike_rate,
        ROUND(s.recent_sr, 1)       AS recent_strike_rate,
        s.improving_q,
        s.declining_q,
        s.stable_q,
        CASE WHEN s.recent_avg > s.early_avg * 1.1 THEN 'Career Ascending'
             WHEN s.recent_avg < s.early_avg * 0.9 THEN 'Career Declining'
             ELSE 'Career Stable' END                                    AS career_phase
FROM    summary    s
JOIN    dim_player p ON p.player_id = s.player_id
ORDER BY s.recent_avg - s.early_avg DESC;
