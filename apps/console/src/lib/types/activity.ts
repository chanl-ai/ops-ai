/** One thing that happened, from agents-service `GET /v1/activity` (one list of runs, chats, emails and decisions). */
export type ActivityKind = 'workflow_run' | 'agent_run' | 'chat' | 'email' | 'decision' | 'tool_call' | 'case' | 'reminder' | 'system_workflow' | 'background';
export type ActivityStatus = 'running' | 'waiting' | 'done' | 'failed' | 'skipped';

export interface ActivityRow {
  /** `<kind>:<source id>`, since ids from different tables can collide. */
  id: string;
  kind: ActivityKind;
  title: string;
  status: ActivityStatus;
  /** The source's own word: succeeded, cancelled, duplicate, filtered, daily_cap, approved, rejected… */
  outcome: string;
  /** The outcome as people read it ("Daily cap"), worded by the API; `outcome` stays the key. */
  outcomeText?: string | null;
  teamId: string;
  source: { type: 'workflow' | 'agent' | 'channel' | 'tool' | 'case' | 'process'; id: string; name: string };
  /** Who or what did it, by name: a person, a mail trigger or sender, another run (with its run id), an agent or a key. */
  actor: { kind: 'person' | 'trigger' | 'sender' | 'run' | 'agent' | 'key' | 'event'; id: string; name: string; runId?: string };
  at: string;
  /** What the row opens; the console maps it to a page. */
  /** `process`: a background process's job, which opens nothing. */
  ref: { kind: 'run' | 'thread' | 'chat' | 'review' | 'email' | 'case' | 'workflow' | 'process'; id: string };
}

export interface ActivityFilters {
  kind?: string[];
  status?: string[];
  /** `type:id`, e.g. `channel:mbx_7f3a` or `workflow:levy_case`. */
  source?: string[];
}

/** Running while the last pass is within two intervals, late after that, stopped after five or while its last pass failed. */
export type BackgroundState = 'running' | 'late' | 'stopped' | 'not_reported';

/** One background process and its heartbeat, from agents-service `GET /v1/background` (c-516). Times are Unix seconds. */
export interface BackgroundProcess {
  key: string;
  service: string;
  title: string;
  does: string;
  /** How often it runs; null for one that runs on events. */
  everySeconds: number | null;
  state: BackgroundState;
  instances: number;
  lastRunAt: number | null;
  nextRunAt: number | null;
  doneHour: number;
  waiting: number | null;
  lastError: string | null;
  lastErrorAt: number | null;
}

/** One piece of work a process did for a team. */
export interface BackgroundJob {
  id: string;
  process: string;
  processTitle: string;
  summary: string;
  outcome: 'done' | 'retried' | 'failed';
  teamId: string;
  teamName: string | null;
  at: string;
}

export interface BackgroundView {
  processes: BackgroundProcess[];
  jobs: BackgroundJob[];
  /** Services whose processes could not be read; theirs show as not reported. */
  unreachable: string[];
}
