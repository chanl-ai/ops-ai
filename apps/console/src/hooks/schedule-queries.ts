'use client';

import { keepPreviousData, useMutation, useQueryClient } from '@tanstack/react-query';
import * as React from 'react';

import { api } from '@/lib/api';
import type { OptionSource } from '@/hooks/options-queries';
import { useTeamQuery } from '@/hooks/team-query';
import type { EngineDefinition } from '@/lib/types/engine';
import type { ScheduleRule } from '@/lib/types/schedules';

/** The time zones a rule may name, searched by the service that checks them. */
export const zoneOptions: OptionSource = { key: 'schedule-zones', fetch: (p) => api.schedules.zones(p) };

/** A value held back until it stops changing, so a preview is asked for once the person pauses typing. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [held, setHeld] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setHeld(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return held;
}

/** The server's words and next runs for the rule on screen. The last answer stays while the next is asked for. */
export function useSchedulePreview(rule: ScheduleRule | null) {
  const held = useDebounced(rule);
  return useTeamQuery({ queryKey: ['schedules', 'preview', held], queryFn: () => api.schedules.preview(held as ScheduleRule), enabled: held !== null, retry: false, placeholderData: keepPreviousData });
}

/** What a save or a clear changes: the workflow's view (its schedules and idle reasons) and every live list. */
function useRefreshAfter(workflowId: string) {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['engine', 'definition', workflowId] }), qc.invalidateQueries({ queryKey: ['channels'] })]);
}

export function useSaveSchedule(workflowId: string, step: string) {
  const refresh = useRefreshAfter(workflowId);
  return useMutation({ mutationFn: (rule: ScheduleRule) => api.schedules.save(workflowId, step, rule), onSuccess: refresh });
}

export function useClearSchedule(workflowId: string, step: string) {
  const refresh = useRefreshAfter(workflowId);
  return useMutation({ mutationFn: () => api.schedules.clear(workflowId, step), onSuccess: refresh });
}

/**
 * Makes the workflow that runs an agent on a schedule: the rule is checked first (a refusal shows before anything is
 * made), then the workflow is stored and the schedule saved on its trigger. A schedule that fails to save leaves the
 * workflow made, and the error says so; the editor sets it.
 */
export function useCreateScheduledWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ definition, rule }: { definition: EngineDefinition; rule: ScheduleRule }) => {
      await api.schedules.preview(rule);
      const stored = await api.engine.publish(definition);
      let saveError: string | null = null;
      try {
        await api.schedules.save(stored.workflowId, 'start', rule);
      } catch (e) {
        saveError = e instanceof Error ? e.message : 'try again in the editor';
      }
      return { workflowId: stored.workflowId, saveError };
    },
    onSettled: () => Promise.all([qc.invalidateQueries({ queryKey: ['channels'] }), qc.invalidateQueries({ queryKey: ['workflows'] })]),
  });
}
