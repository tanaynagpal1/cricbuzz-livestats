-- id: 1
-- title: Players who represent India
-- question: Find all players who represent India. Display their full name, playing role, batting style, and bowling style.
-- params: none

SELECT  player_name,
        gender,
        playing_role,
        batting_style,
        bowling_style
FROM    dim_player
WHERE   primary_team = 'India'
ORDER BY gender DESC, player_name;
