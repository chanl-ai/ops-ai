/** One thing that happened, from agents-service `GET /v1/activity` (one list of runs, chats, emails and decisions). */
export type ActivityKind = 'workflow_run' | 'agent_run' | 'chat' | 'email' | 'decision' | 'tool_call' | 'case' | 'reminder' | 'system_workflow';
export type ActivityStatus = 'running' | 'waiting' | 'done' | 'failed' | 'skipped';

export interface ActivityRow {
  /** `<kind>:<source id>`, since ids from different tables can collide. */
  id: string;
  kind: ActivityKind;
  title: string;
  status: ActivityStatus;
  /** The source's own word: succeeded, cancelled, duplicate, filtered, daily_cap, approved, rejected… */
  outcome: string;
  teamId: string;
  source: { type: 'workflow' | 'agent' | 'channel' | 'tool' | 'case'; id: string; name: string };
  /** Who or what did it, by name: a person, a mail trigger or sender, another run (with its run id), an agent or a key. */
  actor: { kind: 'person' | 'trigger' | 'sender' | 'run' | 'agent' | 'key' | 'event'; id: string; name: string; runId?: string };
  at: string;
  /** What the row opens; the console maps it to a page. */
  ref: { kind: 'run' | 'thread' | 'chat' | 'review' | 'email' | 'case' | 'workflow'; id: string };
}

export interface ActivityFilters {
  kind?: string[];
  status?: string[];
  /** `type:id`, e.g. `channel:mbx_7f3a` or `workflow:levy_case`. */
  source?: string[];
}
