import type { BackgroundView } from '@/lib/types/activity';

const now = () => Date.now() / 1000;
const iso = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();

/** The account's background processes as agents-service reports them, one late and one stopped, for the mock stack. */
export function sampleBackground(): BackgroundView {
  const t = now();
  const p = (key: string, service: string, title: string, does: string, everySeconds: number | null, extra: Partial<BackgroundView['processes'][number]> = {}) => ({
    key, service, title, does, everySeconds, state: 'running' as const, instances: 1, lastRunAt: t - 2, nextRunAt: everySeconds ? t + everySeconds : null, doneHour: 0, waiting: 0, lastError: null, lastErrorAt: null, ...extra,
  });
  return {
    processes: [
      p('workflow_worker', 'agents', 'Workflow worker', 'Runs workflow steps and agent turns that are waiting.', 0.5, { doneHour: 1204, waiting: 3 }),
      p('sweeper', 'agents', 'Sweeper', 'Picks up runs whose worker stopped, and finishes or retries them.', 3, { doneHour: 4, instances: 2 }),
      p('timer_poller', 'agents', 'Timer poller', 'Wakes runs waiting for a time, a date or a reminder.', 1, { doneHour: 37, instances: 2 }),
      p('memory_cleanup', 'agents', 'Memory clean-up', 'Deletes agent memories past their retention.', 3600, { lastRunAt: t - 1440, doneHour: 12, waiting: null }),
      p('mail_listener', 'agents', 'Mail listener', 'Reads each connected mailbox and starts the workflow bound to it.', 30, { state: 'late', lastRunAt: t - 75, doneHour: 11, waiting: 2 }),
      p('event_workflows', 'agents', 'Event workflows', 'Runs the five built-in event workflows.', null, { lastRunAt: t - 60, doneHour: 14, waiting: null }),
      p('files_relay', 'files', 'File hand-off', 'Tells other services a file arrived, changed or was deleted.', 2, { state: 'stopped', lastRunAt: t - 540, waiting: 46, lastError: 'ConnectionRefusedError', lastErrorAt: t - 30 }),
      p('documents_relay', 'documents', 'Document hand-off', 'Tells other services what a document read found.', 2, { doneHour: 19 }),
      p('tools_relay', 'tools', 'Tool events', 'Sends tool-call and access events on.', 2, { doneHour: 88 }),
      p('document_reading', 'documents', 'Document reading', 'Reads queued files and runs document type tests.', null, { lastRunAt: t - 40, doneHour: 26, waiting: 1 }),
    ],
    jobs: [
      { id: 'bjob_1', process: 'event_workflows', processTitle: 'Event workflows', summary: 'Ran Purge a deleted file\'s records for a deleted file', outcome: 'done', teamId: 'team_finance', teamName: 'Finance', at: iso(60) },
      { id: 'bjob_2', process: 'timer_poller', processTitle: 'Timer poller', summary: 'Woke a run that was waiting for a time or a reminder', outcome: 'done', teamId: 'team_people', teamName: 'People team', at: iso(70) },
      { id: 'bjob_3', process: 'mail_listener', processTitle: 'Mail listener', summary: 'Started Insurance claim intake from a new email', outcome: 'done', teamId: 'team_claims', teamName: 'Claims', at: iso(120) },
      { id: 'bjob_4', process: 'sweeper', processTitle: 'Sweeper', summary: 'Picked up a run whose worker stopped, and ran it to its end', outcome: 'done', teamId: 'team_it', teamName: 'IT service desk', at: iso(240) },
    ],
    unreachable: [],
  };
}
