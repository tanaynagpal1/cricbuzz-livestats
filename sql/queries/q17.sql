-- id: 17
-- title: Does winning the toss help?
-- question: What percentage of matches are won by the toss winner, broken down by toss decision (bat first or bowl first)?
-- params: none

-- Matches with no winner (no result, abandoned, tie) are excluded: they
-- can't be won by anyone, so they would drag every percentage down.
SELECT  CASE toss_decision WHEN 'bat'   THEN 'Chose to bat first'
                           WHEN 'field' THEN 'Chose to bowl first' END   AS toss_decision,
        COUNT(*)                                                         AS matches,
        COUNT(*) FILTER (WHERE toss_winner_id = winner_id)               AS toss_winner_won,
        ROUND(100.0 * COUNT(*) FILTER (WHERE toss_winner_id = winner_id)
              / COUNT(*), 2)                                             AS win_pct
FROM    fact_match
WHERE   winner_id IS NOT NULL
  AND   toss_decision IS NOT NULL
GROUP BY toss_decision
ORDER BY toss_decision;
