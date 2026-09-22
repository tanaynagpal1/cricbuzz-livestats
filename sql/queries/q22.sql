-- id: 22
-- title: Head-to-head records (last 3 years)
-- question: For team pairs with 5+ matches in the last 3 years: matches, wins each, average victory margin, wins batting first vs chasing, venues used, and win % for each team.
-- params: none

-- Each pair is stored once, lower team_id first (team_a), so India–Australia
-- and Australia–India count as the same rivalry. "Last 3 years" counts back
-- from the latest match in the archive. Margins are split into runs and
-- wickets, because averaging "40 runs" with "6 wickets" means nothing.
WITH recent AS (
    SELECT  m.*,
            LEAST(m.team1_id, m.team2_id)    AS team_a,
            GREATEST(m.team1_id, m.team2_id) AS team_b,
            i.batting_team_id                AS batted_first
    FROM    fact_match   m
    JOIN    fact_innings i ON i.match_id = m.match_id AND i.innings_no = 1
    WHERE   m.match_date >= (SELECT MAX(match_date) FROM fact_match) - INTERVAL '3 years'
)
SELECT  ta.team_display                                                         AS team_a,
        tb.team_display                                                         AS team_b,
        COUNT(*)                                                                AS matches,
        COUNT(DISTINCT r.venue_id)                                              AS venues,
        COUNT(*) FILTER (WHERE winner_id = team_a)                              AS team_a_wins,
        COUNT(*) FILTER (WHERE winner_id = team_b)                              AS team_b_wins,
        ROUND(100.0 * COUNT(*) FILTER (WHERE winner_id = team_a) / COUNT(*), 1) AS team_a_win_pct,
        ROUND(100.0 * COUNT(*) FILTER (WHERE winner_id = team_b) / COUNT(*), 1) AS team_b_win_pct,
        ROUND(AVG(victory_margin) FILTER (WHERE winner_id = team_a AND victory_type = 'runs'), 1)    AS a_avg_win_runs,
        ROUND(AVG(victory_margin) FILTER (WHERE winner_id = team_a AND victory_type = 'wickets'), 1) AS a_avg_win_wkts,
        ROUND(AVG(victory_margin) FILTER (WHERE winner_id = team_b AND victory_type = 'runs'), 1)    AS b_avg_win_runs,
        ROUND(AVG(victory_margin) FILTER (WHERE winner_id = team_b AND victory_type = 'wickets'), 1) AS b_avg_win_wkts,
        COUNT(*) FILTER (WHERE winner_id = team_a AND batted_first =  team_a)  AS a_wins_batting_first,
        COUNT(*) FILTER (WHERE winner_id = team_a AND batted_first <> team_a)  AS a_wins_chasing,
        COUNT(*) FILTER (WHERE winner_id = team_b AND batted_first =  team_b)  AS b_wins_batting_first,
        COUNT(*) FILTER (WHERE winner_id = team_b AND batted_first <> team_b)  AS b_wins_chasing
FROM    recent   r
JOIN    dim_team ta ON ta.team_id = r.team_a
JOIN    dim_team tb ON tb.team_id = r.team_b
GROUP BY ta.team_display, tb.team_display
HAVING  COUNT(*) >= 5
ORDER BY matches DESC, team_a;
