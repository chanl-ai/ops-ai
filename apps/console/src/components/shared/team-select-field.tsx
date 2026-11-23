'use client';

import { FormField } from '@/components/shared/form-field';
import { SearchSelect } from '@/components/shared/search-select';
import { teamOptions } from '@/hooks/options-queries';

/** A team as a form holds it: its id and the name its trigger shows. */
export type PickedTeam = { id: string; label: string };

/**
 * Team picker for forms opened in Platform scope, where a new record has no team of its own: the person's teams,
 * searched on the server. `allowed` names the teams the form may act in; the others show why they cannot be picked.
 */
export function TeamSelectField({ id, value, onChange, hint, allowed, reason }: { id: string; value: PickedTeam | null; onChange: (team: PickedTeam) => void; hint?: string; allowed?: string[]; reason?: string }) {
  return (
    <FormField id={id} label="Team" hint={hint}>
      <SearchSelect id={id} source={teamOptions(allowed, reason)} value={value} onChange={(teamId, o) => onChange({ id: teamId, label: o?.label ?? teamId })} placeholder="Choose a team" searchPlaceholder="Search teams…" emptyText="No team matches." className="w-full" />
    </FormField>
  );
}
