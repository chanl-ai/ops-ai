'use client';

import * as React from 'react';

import { FormField, FormFieldGroup } from '@/components/shared/form-field';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

import { DAYS, DAY_NAMES, type EveryFormValue } from './every-rule';

/**
 * The fields of an Every rule: a number and a unit, the time it starts at, the weekdays and the hours it runs between.
 * `errors` is the server's refusal by field, shown under the field it names; nothing typed is cleared by one.
 */
export function EveryForm({ value, onChange, errors, disabled, idPrefix }: { value: EveryFormValue; onChange: (v: EveryFormValue) => void; errors: Record<string, string>; disabled?: boolean; idPrefix: string }) {
  const set = (patch: Partial<EveryFormValue>) => onChange({ ...value, ...patch });
  const id = (name: string) => `${idPrefix}-${name}`;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="schedule-every-form">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-3">
        <FormField id={id('every')} label="Every" error={errors.every} hint="Every hour unless you change it.">
          <Input id={id('every')} type="number" inputMode="numeric" min={1} value={value.every} disabled={disabled} aria-invalid={!!errors.every} onChange={(e) => set({ every: e.target.value })} />
        </FormField>
        <FormField id={id('unit')} label="Unit" error={errors.unit}>
          <Select value={value.unit} disabled={disabled} onValueChange={(unit) => set({ unit: unit as EveryFormValue['unit'] })}>
            <SelectTrigger id={id('unit')} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="minutes">minutes</SelectItem>
              <SelectItem value="hours">hours</SelectItem>
              <SelectItem value="days">days</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
      </div>
      <FormField id={id('start')} label="Starting at" optional error={errors.start}>
        <Input id={id('start')} type="time" value={value.start} disabled={disabled} aria-invalid={!!errors.start} onChange={(e) => set({ start: e.target.value })} />
      </FormField>
      <FormFieldGroup label="Days" error={errors.days} hint="Every day, day and night. Untick days or set hours to narrow it.">
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {DAYS.map((d) => (
            <div key={d} className="flex items-center gap-2">
              <Checkbox id={id(`day-${d}`)} checked={value.days.includes(d)} disabled={disabled} onCheckedChange={(on) => set({ days: on ? [...value.days, d] : value.days.filter((x) => x !== d) })} />
              <Label htmlFor={id(`day-${d}`)} className="font-normal">
                {DAY_NAMES[d].slice(0, 3)}
                <span className="sr-only">{DAY_NAMES[d].slice(3)}</span>
              </Label>
            </div>
          ))}
        </div>
      </FormFieldGroup>
      <FormFieldGroup label="Between" optional error={errors.between}>
        <div className="grid grid-cols-2 gap-3">
          <Input id={id('from')} type="time" aria-label="Between, from" value={value.from} disabled={disabled} aria-invalid={!!errors.between} onChange={(e) => set({ from: e.target.value })} />
          <Input id={id('to')} type="time" aria-label="Between, to" value={value.to} disabled={disabled} aria-invalid={!!errors.between} onChange={(e) => set({ to: e.target.value })} />
        </div>
      </FormFieldGroup>
    </div>
  );
}
