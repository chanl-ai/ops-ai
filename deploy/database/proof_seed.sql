-- Rows for deploy/database/proof.sh check 2, on the FROM baseline (agents head 0115): one table per fill a later step
-- runs, with values that reach each branch of it. proof.sh holds the expected result.
-- agents 0117: counts from summary; a number is truncated, true is 1, anything else (a string, not an object) is 0.
INSERT INTO registry_validations (tenant_id, id, workflow_id, ran_at, target, results, summary) VALUES
  ('t1', 'v1', 'w1', '2026-11-16T00:00:00Z', 'draft', '[]',
   '{"passed": 3, "total": 4.9, "regressions": true, "checksFailing": "2"}'),
  ('t2', 'v2', 'w2', '2026-11-16T00:00:00Z', 'draft', '[]', '[1, 2]');
-- agents 0118: the first Email received node's mailbox; nodes that are not a list name none.
INSERT INTO engine_definitions
  (tenant_id, workflow_id, version, digest, name, definition, created_at, created_by, team_id, stage,
   description, trigger, startable, takes_files) VALUES
  ('t1', 'w1', 1, 'd1', 'Inbox',
   '{"nodes": [{"type": "ops.trigger.manual"}, {"type": "ops.trigger.email", "parameters": {"mailbox": "help@example.com"}},
     {"type": "ops.trigger.email", "parameters": {"mailbox": "second@example.com"}}]}',
   '2026-11-16T00:00:00Z', 'p1', 'team1', 'live', '', '', false, false),
  ('t2', 'w2', 1, 'd2', 'None', '{"nodes": "x"}', '2026-11-16T00:00:00Z', 'p2', NULL, 'draft', '', '', false, false);
