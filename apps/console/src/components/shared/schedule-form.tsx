'use client';

import * as React from 'react';

import { FormField } from '@/components/shared/form-field';
import { SearchSelect } from '@/components/shared/search-select';
import { Skeleton } from '@/components/ui/skeleton';
import { zoneOptions } from '@/hooks/schedule-queries';
import { dateTime } from '@/lib/format';
import type { SchedulePreview } from '@/lib/types/schedules';

import { EveryForm } from './schedule-forms/every-form';
import { type EveryFormValue } from './schedule-forms/every-rule';

/** The browser's own time zone, where Time zone opens; a zone the service does not know is refused beside the field. */
export const localTimeZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
};

/**
 * The schedule form: the rule kind's fields, Time zone as a search over the service's zones, then what the server makes of it,
 * the words and the next three runs. Only the Every kind has a form today, so no kind is asked for.
 */
export function ScheduleForm({
  value,
  onChange,
  errors,
  disabled,
  idPrefix,
  preview,
  previewing,
  nextRunsNote,
}: {
  value: EveryFormValue;
  onChange: (v: EveryFormValue) => void;
  /** The server's refusal by field name. */
  errors: Record<string, string>;
  disabled?: boolean;
  idPrefix: string;
  preview: SchedulePreview | undefined;
  previewing: boolean;
  /** Replaces the next runs, for a paused workflow: "None while paused". */
  nextRunsNote?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="schedule-form">
      <EveryForm value={value} onChange={onChange} errors={errors} disabled={disabled} idPrefix={idPrefix} />
      <FormField id={`${idPrefix}-tz`} label="Time zone" error={errors.tz}>
        <SearchSelect
          id={`${idPrefix}-tz`}
          source={zoneOptions}
          value={value.tz ? { id: value.tz, label: value.tz } : null}
          onChange={(tz) => onChange({ ...value, tz })}
          placeholder="Choose a time zone"
          searchPlaceholder="Search time zones…"
          disabled={disabled}
          testId="schedule-zone"
          ariaLabel="Time zone"
        />
      </FormField>
      <div className="flex flex-col gap-1.5" aria-live="polite" data-testid="schedule-next-runs">
        <p className="text-sm font-medium">Next runs</p>
        {nextRunsNote ? (
          <p className="text-sm text-muted-foreground">{nextRunsNote}</p>
        ) : previewing && !preview ? (
          <Skeleton className="h-12 w-full" />
        ) : preview ? (
          <>
            <p className="text-sm text-muted-foreground" data-testid="schedule-words">{preview.words}</p>
            <ul className="text-sm tabular-nums">
              {preview.nextRuns.map((t) => (
                <li key={t}>{dateTime(t)}</li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Fix the fields above to see the next runs.</p>
        )}
      </div>
    </div>
  );
}
