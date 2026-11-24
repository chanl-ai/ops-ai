import type { OptionsPage, OptionsParams } from '../types/query';
import type { SchedulePreview, ScheduleRule, ScheduleView } from '../types/schedules';

/** Saved schedules on agents-service: the rule kinds' preview, the time zones, and a trigger step's save and clear. */
export interface SchedulesApi {
  /** The rule in words with its next runs, from the server's own rule; a refusal is an ApiError naming `details.field`. */
  preview(rule: ScheduleRule): Promise<SchedulePreview>;
  /** The time zones a rule may name, searched and paged by the service that checks them. */
  zones(params: OptionsParams): Promise<OptionsPage>;
  /** Saves the rule on a trigger step; it applies at once to the live version. */
  save(workflowId: string, step: string, rule: ScheduleRule): Promise<ScheduleView>;
  clear(workflowId: string, step: string): Promise<void>;
}
