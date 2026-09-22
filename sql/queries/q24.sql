-- id: 24
-- title: Best batting partnerships
-- question: For pairs of consecutive batsmen (positions differ by 1) with 5+ partnerships: average runs, stands over 50, highest stand and success rate. Rank the best pairs.
-- params: none

-- LEAST/GREATEST put each pair in a fixed order, so "Rohit & Dhawan" and
-- "Dhawan & Rohit" are counted as one pair. Success rate = share of their
-- stands that reached 50 (a "good" partnership).
WITH stands AS (
    SELECT  LEAST(pt.batter1_id, pt.batter2_id)    AS player_a,
            GREATEST(pt.batter1_id, pt.batter2_id) AS player_b,
            pt.runs
    FROM    fact_partnership pt
    JOIN    fact_batting b1 ON b1.match_id = pt.match_id AND b1.innings_no = pt.innings_no
                           AND b1.player_id = pt.batter1_id
    JOIN    fact_batting b2 ON b2.match_id = pt.match_id AND b2.innings_no = pt.innings_no
                           AND b2.player_id = pt.batter2_id
    WHERE   ABS(b1.batting_position - b2.batting_position) = 1
)
SELECT  RANK() OVER (ORDER BY AVG(s.runs) DESC)                  AS rank,
        pa.player_name || ' & ' || pb.player_name                 AS pair,
        COUNT(*)                                                  AS partnerships,
        ROUND(AVG(s.runs), 1)                                     AS avg_runs,
        COUNT(*) FILTER (WHERE s.runs >= 50)                      AS fifty_plus_stands,
        MAX(s.runs)                                               AS highest,
        ROUND(100.0 * COUNT(*) FILTER (WHERE s.runs >= 50) / COUNT(*), 1) AS success_rate_pct
FROM    stands     s
JOIN    dim_player pa ON pa.player_id = s.player_a
JOIN    dim_player pb ON pb.player_id = s.player_b
GROUP BY s.player_a, s.player_b, pa.player_name, pb.player_name
HAVING  COUNT(*) >= 5
ORDER BY rank;
