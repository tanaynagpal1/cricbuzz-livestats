-- id: 6
-- title: Players by playing role
-- question: Count how many players belong to each playing role.
-- params: none

-- Roles are worked out from what players actually did (how much they
-- bowled, where they batted, how many catches and stumpings), because the
-- source does not record an official role. "Unknown" = too few matches.
SELECT  playing_role,
        COUNT(*) AS players
FROM    dim_player
GROUP BY playing_role
ORDER BY players DESC;
