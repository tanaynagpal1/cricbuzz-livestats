-- id: 7
-- title: Highest individual score by format
-- question: Find the highest individual batting score in each cricket format (Test, ODI, T20I).
-- params: none

-- The archive holds ODIs only, so one row comes back. The query itself is
-- written for any number of formats.
SELECT  m.match_format        AS format,
        MAX(b.runs_scored)    AS highest_score
FROM    fact_batting b
JOIN    fact_match   m ON m.match_id = b.match_id
GROUP BY m.match_format
ORDER BY m.match_format;
