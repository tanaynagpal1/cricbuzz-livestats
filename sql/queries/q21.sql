-- id: 21
-- title: Overall player ranking
-- question: Rank players in each format with one weighted score combining batting (runs, average, strike rate), bowling (wickets, average, economy) and fielding (catches, stumpings).
-- params: none

-- Formula from the brief:
--   batting  = runs × 0.01 + batting_avg × 0.5 + strike_rate × 0.3
--   bowling  = wickets × 2 + (50 − bowling_avg) × 0.5 + (6 − economy) × 2
--   fielding = catches × 3 + stumpings × 5
-- Bowling points apply only to players who have taken a wicket (a bowling
-- average needs at least one). Minimum 20 matches so the ranking isn't led
-- by someone with one great game. Top 25 per format.
WITH appearances AS (
    SELECT match_id, player_id FROM fact_batting
    UNION                                   -- UNION removes duplicates
    SELECT match_id, player_id FROM fact_bowling
),
matches AS (
    SELECT  a.player_id, m.match_format, COUNT(*) AS matches
    FROM    appearances a
    JOIN    fact_match  m ON m.match_id = a.match_id
    GROUP BY a.player_id, m.match_format
),
batting AS (
    SELECT  b.player_id, m.match_format,
            SUM(b.runs_scored)                                   AS runs,
            SUM(b.runs_scored)::numeric
              / NULLIF(COUNT(*) FILTER (WHERE NOT b.is_not_out), 0) AS bat_avg,
            SUM(b.runs_scored) * 100.0 / NULLIF(SUM(b.balls_faced), 0) AS strike_rate
    FROM    fact_batting b
    JOIN    fact_match   m ON m.match_id = b.match_id
    GROUP BY b.player_id, m.match_format
),
bowling AS (
    SELECT  w.player_id, m.match_format,
            SUM(w.wickets)                                           AS wickets,
            SUM(w.runs_conceded)::numeric / NULLIF(SUM(w.wickets), 0) AS bowl_avg,
            SUM(w.runs_conceded) * 6.0 / NULLIF(SUM(w.balls_bowled), 0) AS economy
    FROM    fact_bowling w
    JOIN    fact_match   m ON m.match_id = w.match_id
    GROUP BY w.player_id, m.match_format
),
fielding AS (
    -- A catch is credited to the fielder; in "caught and bowled" the bowler
    -- is the catcher.
    SELECT  CASE WHEN b.dismissal_kind = 'caught and bowled'
                 THEN b.dismissed_by_id ELSE b.fielder_id END   AS player_id,
            m.match_format,
            COUNT(*) FILTER (WHERE b.dismissal_kind IN ('caught', 'caught and bowled')) AS catches,
            COUNT(*) FILTER (WHERE b.dismissal_kind = 'stumped')                       AS stumpings
    FROM    fact_batting b
    JOIN    fact_match   m ON m.match_id = b.match_id
    WHERE   b.dismissal_kind IN ('caught', 'caught and bowled', 'stumped')
    GROUP BY 1, m.match_format
),
scored AS (
    SELECT  mt.player_id, mt.match_format, mt.matches,
            COALESCE(bt.runs, 0)            AS runs,
            COALESCE(bw.wickets, 0)         AS wickets,
            COALESCE(f.catches, 0)          AS catches,
            COALESCE(f.stumpings, 0)        AS stumpings,
            COALESCE(bt.runs * 0.01 + COALESCE(bt.bat_avg, 0) * 0.5
                     + COALESCE(bt.strike_rate, 0) * 0.3, 0)                 AS batting_pts,
            CASE WHEN bw.wickets > 0
                 THEN bw.wickets * 2 + (50 - bw.bowl_avg) * 0.5 + (6 - bw.economy) * 2
                 ELSE 0 END                                                  AS bowling_pts,
            COALESCE(f.catches, 0) * 3 + COALESCE(f.stumpings, 0) * 5       AS fielding_pts
    FROM    matches mt
    LEFT JOIN batting  bt ON bt.player_id = mt.player_id AND bt.match_format = mt.match_format
    LEFT JOIN bowling  bw ON bw.player_id = mt.player_id AND bw.match_format = mt.match_format
    LEFT JOIN fielding f  ON f.player_id  = mt.player_id AND f.match_format  = mt.match_format
    WHERE   mt.matches >= 20
),
ranked AS (
    SELECT  s.*,
            batting_pts + bowling_pts + fielding_pts                          AS total_score,
            RANK() OVER (PARTITION BY match_format
                         ORDER BY batting_pts + bowling_pts + fielding_pts DESC) AS format_rank
    FROM    scored s
)
SELECT  r.match_format                  AS format,
        r.format_rank                   AS rank,
        p.player_name,
        p.playing_role,
        r.matches, r.runs, r.wickets, r.catches, r.stumpings,
        ROUND(r.batting_pts, 1)         AS batting_pts,
        ROUND(r.bowling_pts, 1)         AS bowling_pts,
        ROUND(r.fielding_pts, 1)        AS fielding_pts,
        ROUND(r.total_score, 1)         AS total_score
FROM    ranked     r
JOIN    dim_player p ON p.player_id = r.player_id
WHERE   r.format_rank <= 25
ORDER BY r.match_format, r.format_rank;
