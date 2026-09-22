-- Indexes for fact_over, applied AFTER the bulk load (faster than
-- maintaining them during 274,000 inserts).

-- "Every over bowled by this player" — bowling by phase in the Player Lab.
CREATE INDEX IF NOT EXISTS ix_fact_over_bowler  ON fact_over (bowler_id);

-- "Every over of this team's innings" — era charts filtered by team.
CREATE INDEX IF NOT EXISTS ix_fact_over_batting ON fact_over (batting_team_id);

-- One match's overs come straight off the primary key (match_id first),
-- so the worm and Manhattan need no extra index.

ANALYZE fact_over;