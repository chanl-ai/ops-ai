'use client';

import { SCHEDULE_KIND_LABEL, WEEKDAY_LABEL } from '@/components/knowledge/knowledge-meta';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { Schedule, Weekday } from '@/lib/types/knowledge';

const HOURS = [1, 2, 4, 6, 12] as const;

/** The browser's time zone, which a new daily or weekly schedule starts in. */
export const localTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

/** A schedule of `kind`, keeping the time and zone of the one it replaces. */
export function scheduleOfKind(kind: Schedule['kind'], from: Schedule): Schedule {
  const time = from.kind === 'daily' || from.kind === 'weekly' ? from.time : '02:00';
  const tz = from.kind === 'daily' || from.kind === 'weekly' ? from.tz : localTimeZone();
  if (kind === 'manual') return { kind };
  if (kind === 'hourly') return { kind, every: from.kind === 'hourly' ? from.every : 4 };
  if (kind === 'daily') return { kind, time, tz };
  return { kind, day: from.kind === 'weekly' ? from.day : 'mon', time, tz };
}

/** When a source syncs on its own: manual, every 1 to 12 hours, daily at a time, or weekly on a day, in a time zone. */
export function SchedulePicker({ id, value, onChange, disabled }: { id: string; value: Schedule; onChange: (s: Schedule) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={value.kind} onValueChange={(k) => onChange(scheduleOfKind(k as Schedule['kind'], value))} disabled={disabled}>
        <SelectTrigger id={id} className="w-44 bg-background" aria-label="Sync">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(SCHEDULE_KIND_LABEL) as Schedule['kind'][]).map((k) => (
            <SelectItem key={k} value={k}>
              {SCHEDULE_KIND_LABEL[k]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {value.kind === 'hourly' && (
        <Select value={String(value.every)} onValueChange={(v) => onChange({ kind: 'hourly', every: Number(v) as (typeof HOURS)[number] })} disabled={disabled}>
          <SelectTrigger className="w-36 bg-background" aria-label="Every">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {HOURS.map((h) => (
              <SelectItem key={h} value={String(h)}>
                {h === 1 ? 'Every hour' : `Every ${h} hours`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {value.kind === 'weekly' && (
        <Select value={value.day} onValueChange={(d) => onChange({ ...value, day: d as Weekday })} disabled={disabled}>
          <SelectTrigger className="w-36 bg-background" aria-label="Day">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(WEEKDAY_LABEL) as Weekday[]).map((d) => (
              <SelectItem key={d} value={d}>
                {WEEKDAY_LABEL[d]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {(value.kind === 'daily' || value.kind === 'weekly') && (
        <>
          <Input type="time" className="w-32 bg-background" value={value.time} aria-label="Time" disabled={disabled} onChange={(e) => onChange({ ...value, time: e.target.value || '02:00' })} />
          <span className="text-sm text-muted-foreground">{value.tz}</span>
        </>
      )}
    </div>
  );
}
