-- id: 4
-- title: Venues with capacity over 50,000
-- question: Display all venues with a seating capacity of more than 50,000. Show venue name, city, country and capacity. Largest first.
-- params: none

-- Capacity is today's figure, not the capacity on the day of each match.
-- 29 small grounds have no published capacity and are left out by the filter.
SELECT  venue_name,
        city,
        country,
        capacity
FROM    dim_venue
WHERE   capacity > 50000
ORDER BY capacity DESC;
