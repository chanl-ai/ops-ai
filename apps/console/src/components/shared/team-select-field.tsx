'use client';

import { FormField } from '@/components/shared/form-field';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

/** Team picker for forms opened in Platform scope, where a new record has no team of its own. */
export function TeamSelectField({ id, teams, value, onChange, hint }: { id: string; teams: { id: string; name: string }[]; value: string; onChange: (id: string) => void; hint?: string }) {
  return (
    <FormField id={id} label="Team" hint={hint}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder="Choose a team" />
        </SelectTrigger>
        <SelectContent>
          {teams.map((t) => (
            <SelectItem key={t.id} value={t.id}>
              {t.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
