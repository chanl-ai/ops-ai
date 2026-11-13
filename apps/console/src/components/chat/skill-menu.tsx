'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { FileText, Lock, Sparkles, X } from 'lucide-react';
import { z } from 'zod';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandItem, CommandList } from '@/components/ui/command';
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useChatMenuSkills } from '@/hooks/skill-queries';
import { ApiError } from '@/lib/api/contract';
import { cn } from '@/lib/utils';
import type { SkillPick } from '@/lib/types/chat';
import type { ChatMenuSkill, SkillInputField } from '@/lib/types/skills';

/** A skill, or one part of it, chosen from the / menu, before and after its inputs are filled. */
export interface PickedSkill {
  skillId: string;
  part?: string;
  /** "Salesforce · Prepare a client meeting", or the skill's name alone. */
  label: string;
  version: number | null;
  fields: SkillInputField[];
  inputs: Record<string, string>;
}

/** What the API takes for the picked skill. */
export const toPick = (p: PickedSkill): SkillPick => ({
  skillId: p.skillId,
  ...(p.part ? { part: p.part } : {}),
  ...(Object.keys(p.inputs).length ? { inputs: p.inputs } : {}),
});

const inputCount = (n: number) => (n === 0 ? 'No inputs' : n === 1 ? '1 input' : `${n} inputs`);
const words = (name: string) => name.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

/** Each pickable row: a skill without parts, or each part of one that has them. */
function entries(s: ChatMenuSkill): PickedSkill[] {
  const version = s.publishedVersion;
  if (s.parts?.length)
    return s.parts.map((p) => ({ skillId: s.id, part: p.slug, label: `${s.name} · ${p.name}`, version, fields: p.inputs, inputs: {} }));
  return [{ skillId: s.id, label: s.name, version, fields: s.inputs ?? [], inputs: {} }];
}

/**
 * The chat's / menu: the published skills the agent may use under its skill menu setting, a skill with parts as a
 * group of its parts. A skill needing a tool or knowledge base the agent lacks is shown locked with what it needs.
 * The composer places it with `className` (above it, or below near the top of the page); `query` is what follows the /.
 */
export function SkillMenu({
  agentId,
  agentName,
  query,
  onPick,
  className,
}: {
  agentId: string;
  agentName: string;
  query: string;
  onPick: (p: PickedSkill) => void;
  className?: string;
}) {
  const menu = useChatMenuSkills(agentId, true);
  const q = query.trim().toLowerCase();
  const has = (...fields: (string | undefined)[]) => fields.join(' ').toLowerCase().includes(q);
  // A skill with parts matches by its own name (all its parts show) or part by part on each part's name and use-when;
  // its general use-when would otherwise pull in parts the search does not describe.
  const skills = (menu.data ?? []).flatMap((sk) => {
    if (!q) return [{ s: sk, rows: entries(sk) }];
    if (!sk.parts?.length) return has(sk.name, sk.slug, sk.useWhen) ? [{ s: sk, rows: entries(sk) }] : [];
    if (has(sk.name, sk.slug)) return [{ s: sk, rows: entries(sk) }];
    const rows = entries(sk).filter((e) => {
      const part = sk.parts!.find((x) => x.slug === e.part)!;
      return has(part.name, part.slug, part.useWhen);
    });
    return rows.length ? [{ s: sk, rows }] : [];
  });
  const refused = menu.error instanceof ApiError && menu.error.status === 403;
  return (
    <div className={cn('absolute inset-x-0 z-10 overflow-hidden rounded-lg border bg-popover shadow-md', className)} data-testid="skill-menu">
      <Command shouldFilter={false} loop>
        <CommandList className="max-h-72">
          {menu.isPending ? (
            <div className="space-y-2 p-3" aria-label="Loading skills">
              <Skeleton className="h-8" />
              <Skeleton className="h-8" />
              <Skeleton className="h-8" />
            </div>
          ) : menu.isError ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">
              {refused ? 'Your role cannot use skills in chat. A team admin can give you skills: view.' : `The skills could not be loaded: ${menu.error.message}`}
            </p>
          ) : (
            <>
              <CommandEmpty>{q ? `No skill matches “${query}”.` : `${agentName} offers no skills in chat. A builder publishes skills, and an admin sets which ones an agent offers.`}</CommandEmpty>
              {skills.map(({ s, rows }) => {
                return (
                  <CommandGroup key={s.id} heading={rows.length > 1 || s.parts?.length ? s.name : s.ownerTeam}>
                    {rows.map((e) => (
                      <CommandItem
                        key={`${e.skillId}/${e.part ?? ''}`}
                        value={`${e.skillId}/${e.part ?? ''}`}
                        disabled={s.locked}
                        onSelect={() => onPick(e)}
                        className="items-start"
                      >
                        {s.locked ? <Lock className="mt-0.5 size-4" /> : <FileText className="mt-0.5 size-4" />}
                        <span className="flex min-w-0 flex-1 flex-col">
                          <span className="truncate font-medium">{s.parts?.length ? e.label.slice(s.name.length + 3) : e.label}</span>
                          <span className="line-clamp-2 text-xs text-muted-foreground">
                            {s.locked ? `Needs ${(s.needs ?? []).join(', ')}, which ${agentName} does not have.` : (s.parts?.find((p) => p.slug === e.part)?.useWhen ?? s.useWhen)}
                          </span>
                        </span>
                        <span className="shrink-0 text-xs text-muted-foreground">{inputCount(e.fields.length)}</span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                );
              })}
            </>
          )}
        </CommandList>
      </Command>
      <div className="border-t px-3 py-1.5 text-xs text-muted-foreground">Published skills {agentName} can use · ↑↓ to move, Enter to pick, Esc to close</div>
    </div>
  );
}

/** The picked skill's inputs, required ones checked before it is added to the message. */
export function SkillInputsForm({ picked, onDone, onBack }: { picked: PickedSkill; onDone: (inputs: Record<string, string>) => void; onBack: () => void }) {
  const schema = React.useMemo(
    () => z.object(Object.fromEntries(picked.fields.map((f) => [f.name, f.required ? z.string().trim().min(1, `${words(f.name)} is required.`) : z.string()]))),
    [picked.fields],
  );
  const form = useForm<Record<string, string>>({
    resolver: zodResolver(schema),
    defaultValues: Object.fromEntries(picked.fields.map((f) => [f.name, picked.inputs[f.name] ?? ''])),
  });
  const submit = form.handleSubmit((values) => onDone(Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()]))));
  return (
    <form
      onSubmit={(e) => void submit(e)}
      onKeyDown={(e) => e.key === 'Escape' && onBack()}
      className="absolute inset-x-0 bottom-full z-10 mb-2 rounded-lg border bg-popover p-4 shadow-md"
      data-testid="skill-inputs"
    >
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Sparkles className="size-4" />
        <span className="truncate">{picked.label}</span>
        {picked.version != null && <Badge variant="outline">v{picked.version}</Badge>}
        <span className="ml-auto text-xs font-normal text-muted-foreground">Esc to cancel</span>
      </div>
      <FieldGroup className="gap-3">
        {picked.fields.map((f, i) => (
          <Controller
            key={f.name}
            name={f.name}
            control={form.control}
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid}>
                <FieldLabel htmlFor={`skill-input-${f.name}`}>
                  {words(f.name)}
                  {f.required && <span className="text-destructive-text">*</span>}
                </FieldLabel>
                <Input {...field} id={`skill-input-${f.name}`} autoFocus={i === 0} aria-invalid={fieldState.invalid} placeholder={f.required ? undefined : 'Optional'} />
                {f.description && <FieldDescription>{f.description}</FieldDescription>}
                <FieldError errors={[fieldState.error]} />
              </Field>
            )}
          />
        ))}
      </FieldGroup>
      <div className="mt-4 flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button type="submit">Add to message</Button>
      </div>
    </form>
  );
}

/** The picked skill as a chip in the composer; `onRemove` drops it from the message. */
export function SkillChip({ label, onRemove }: { label: string; onRemove?: () => void }) {
  return (
    <span className="inline-flex h-6 max-w-full items-center gap-1 rounded-md bg-primary/10 pr-1 pl-1.5 text-sm font-medium text-primary" data-testid="skill-chip">
      <span className="truncate">/{label}</span>
      {onRemove && (
        <Button type="button" variant="ghost" size="icon" className="size-4 rounded-full text-primary hover:bg-primary/15" onClick={onRemove} aria-label={`Remove ${label}`}>
          <X className="size-3" />
        </Button>
      )}
    </span>
  );
}
