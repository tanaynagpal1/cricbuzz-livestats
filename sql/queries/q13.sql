-- id: 13
-- title: 100-run partnerships between consecutive batters
-- question: Find partnerships where two consecutive batsmen (batting positions next to each other) put on 100 or more runs in the same innings.
-- params: none

-- fact_partnership holds real stands (the runs added while the two were
-- at the crease together). fact_batting is joined twice, once per batter,
-- to fetch their batting positions and keep only neighbours (differ by 1).
SELECT  p1.player_name                          AS batter_1,
        p2.player_name                          AS batter_2,
        pt.runs                                 AS partnership_runs,
        pt.innings_no,
        pt.wicket_no                            AS for_wicket,
        tb.team_display                         AS batting_team,
        m.match_date
FROM    fact_partnership pt
JOIN    fact_batting b1 ON b1.match_id = pt.match_id AND b1.innings_no = pt.innings_no
                       AND b1.player_id = pt.batter1_id
JOIN    fact_batting b2 ON b2.match_id = pt.match_id AND b2.innings_no = pt.innings_no
                       AND b2.player_id = pt.batter2_id
JOIN    dim_player  p1 ON p1.player_id = pt.batter1_id
JOIN    dim_player  p2 ON p2.player_id = pt.batter2_id
JOIN    dim_team    tb ON tb.team_id   = pt.batting_team_id
JOIN    fact_match  m  ON m.match_id   = pt.match_id
WHERE   ABS(b1.batting_position - b2.batting_position) = 1
  AND   pt.runs >= 100
ORDER BY pt.runs DESC, m.match_date DESC;
