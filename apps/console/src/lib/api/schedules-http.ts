import type { OptionsPage } from '../types/query';
import type { SchedulePreview, ScheduleView } from '../types/schedules';
import type { SchedulesApi } from './schedules-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** `get` and `send` come from a client whose base URL ends in /v1 on agents-service. */
export function createSchedulesHttp(get: Get, send: Send): SchedulesApi {
  const trigger = (workflowId: string, step: string) => `/workflows/definitions/${encodeURIComponent(workflowId)}/triggers/${encodeURIComponent(step)}/schedule`;
  return {
    preview: (rule) => send<SchedulePreview>('POST', '/schedules/preview', { rule }),
    zones: ({ search, cursor, limit }) => {
      const q = new URLSearchParams();
      if (search) q.set('search', search);
      if (cursor) q.set('cursor', cursor);
      if (limit) q.set('limit', String(Math.min(limit, 50)));
      return get<OptionsPage>(`/schedules/zones${q.size ? `?${q}` : ''}`);
    },
    save: (workflowId, step, rule) => send<ScheduleView>('PUT', trigger(workflowId, step), { rule }),
    clear: async (workflowId, step) => {
      await send('DELETE', trigger(workflowId, step));
    },
  };
}
