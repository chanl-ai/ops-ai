import { ApiError } from '@/lib/api/contract';

/** The fields of the schedule form: a refusal naming one is shown beside it, any other above the form. */
export const SCHEDULE_FIELDS = ['every', 'unit', 'start', 'days', 'between', 'tz'];

/** A refusal split into the field it names (when the form has it) and the rest. */
export function refusalOf(error: unknown): { byField: Record<string, string>; general?: string } {
  if (!(error instanceof ApiError)) return { byField: {}, general: error instanceof Error ? error.message : undefined };
  const field = String(error.details?.field ?? '');
  return SCHEDULE_FIELDS.includes(field) ? { byField: { [field]: error.message } } : { byField: {}, general: error.message };
}
