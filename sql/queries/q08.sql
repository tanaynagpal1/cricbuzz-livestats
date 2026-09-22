-- id: 8
-- title: Series that started in 2024
-- question: Show all series that started in 2024 with series name, host country, match type, start date and total matches.
-- params: none

-- Host country = the country (or countries) where the series' matches were
-- played. "Matches planned" is not in the source; this counts the matches
-- actually played. series_id 0 is the "no series" placeholder and is skipped.
SELECT  s.series_name,
        STRING_AGG(DISTINCT v.country, ', ')      AS host_country,
        MIN(m.match_format)                        AS match_type,
        s.gender,
        s.first_match                              AS start_date,
        COUNT(DISTINCT m.match_id)                 AS total_matches
FROM    dim_series s
JOIN    fact_match m ON m.series_id = s.series_id
JOIN    dim_venue  v ON v.venue_id  = m.venue_id
WHERE   s.series_id <> 0
  AND   EXTRACT(YEAR FROM s.first_match) = 2024
GROUP BY s.series_id, s.series_name, s.gender, s.first_match
ORDER BY s.first_match, s.series_name;
