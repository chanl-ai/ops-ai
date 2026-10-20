'use client';

import { AlertTriangle, Sparkles } from 'lucide-react';

import { QueryError } from '@/components/shared/query-states';
import { AlwaysChip } from '@/components/skills/skill-loading';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { count, plural } from '@/lib/format';
import type { SkillCandidate, SkillCandidates } from '@/lib/types/skills';
import type { SkillPinInput, TemplateSkillSuggestion } from '@/lib/types/templates';
import { cn } from '@/lib/utils';

/** The newest version an agent with the wizard's scope could pin, or undefined when none. */
export const pinnableVersion = (c: SkillCandidate) => c.versions.find((v) => !v.missing.length)?.version;

/** Why a chosen pin cannot be kept with the current tools and knowledge bases; undefined when it can. */
export function pinProblem(pin: SkillPinInput, candidates: SkillCandidates | undefined, names: Record<string, string>) {
  const c = candidates?.attachable.find((x) => x.skillId === pin.skillId);
  const name = c?.name ?? names[pin.skillId] ?? 'This skill';
  if (!c) return `${name} no longer fits this agent. Remove it, or go back to Configure.`;
  const v = c.versions.find((x) => x.version === pin.version);
  if (v?.missing.length) return `${name} v${pin.version} needs ${v.missing.join(', ')}. Grant ${v.missing.length === 1 ? 'it' : 'them'} in Configure, choose another version or remove it.`;
  return undefined;
}

/**
 * Skills step of the new-agent wizard. Lists the published skills an agent with the chosen owner, tools and
 * knowledge bases could pin, with the template's suggestions first. A skill never grants access, so one that
 * needs more is shown with what it needs and a way back to Configure.
 */
export function TemplateSkillsStep({
  candidates,
  loading,
  error,
  onRetry,
  suggestions,
  value,
  onChange,
  onBackToConfigure,
  showErrors,
}: {
  candidates?: SkillCandidates;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  suggestions: TemplateSkillSuggestion[];
  value: SkillPinInput[];
  onChange: (pins: SkillPinInput[]) => void;
  onBackToConfigure: () => void;
  showErrors: boolean;
}) {
  if (error) return <QueryError what="skills" onRetry={onRetry} />;
  if (loading || !candidates)
    return (
      <div className="flex flex-col gap-2" aria-busy="true">
        <Skeleton className="h-5 w-72" />
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    );

  const limit = candidates.limits.maxAttached;
  const names = Object.fromEntries(suggestions.map((s) => [s.skillId, s.name]));
  const suggestedIds = suggestions.map((s) => s.skillId);
  const rest = candidates.attachable.filter((c) => !suggestedIds.includes(c.skillId));
  const blockedSuggestions = suggestions.filter((s) => !candidates.attachable.some((c) => c.skillId === s.skillId));
  const otherBlocked = candidates.blocked.filter((b) => b.kind === 'access' && !suggestedIds.includes(b.skillId));
  const full = value.length >= limit;
  const toggle = (c: SkillCandidate, on: boolean) => {
    const v = pinnableVersion(c);
    if (on && v !== undefined) onChange([...value, { skillId: c.skillId, version: v }]);
    else onChange(value.filter((p) => p.skillId !== c.skillId));
  };
  const setVersion = (skillId: string, version: number) => onChange(value.map((p) => (p.skillId === skillId ? { ...p, version } : p)));

  const row = (c: SkillCandidate, reason?: string) => {
    const pin = value.find((p) => p.skillId === c.skillId);
    const problem = pin && showErrors ? pinProblem(pin, candidates, names) : undefined;
    return (
      <li key={c.skillId} className={cn('flex flex-col gap-1.5 px-3 py-2.5', pin && 'bg-primary/5')} data-testid={`tw-skill-${c.skillId}`}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          <Checkbox id={`tw-skill-${c.skillId}`} checked={!!pin} disabled={!pin && full} onCheckedChange={(on) => toggle(c, !!on)} aria-label={`Attach ${c.name}`} aria-invalid={!!problem} />
          <label htmlFor={`tw-skill-${c.skillId}`} className="min-w-0 flex-1 cursor-pointer text-sm font-medium">
            {c.name}
            {c.ownerTeam === 'Platform' && <span className="ml-1.5 text-xs font-normal text-muted-foreground">Platform</span>}
            <AlwaysChip loading={c.loading} className="ml-1.5 text-[10px] font-normal" />
          </label>
          <span className="text-xs text-muted-foreground tabular-nums">{count(c.tokens)} tokens</span>
          <Select value={String(pin?.version ?? pinnableVersion(c))} onValueChange={(v) => (pin ? setVersion(c.skillId, Number(v)) : onChange([...value, { skillId: c.skillId, version: Number(v) }]))} disabled={!pin && full}>
            <SelectTrigger size="sm" className="w-32 max-w-full" aria-label={`Version of ${c.name}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {c.versions.map((v) => (
                <SelectItem key={v.version} value={String(v.version)} disabled={v.missing.length > 0}>
                  v{v.version}
                  {v.current ? ' · latest' : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="pl-6 text-xs text-muted-foreground">{reason ?? (c.loading === 'always' ? 'Added to every turn, after the agent’s instructions' : c.useWhen)}</p>
        {problem && <p className="pl-6 text-xs text-destructive">{problem}</p>}
      </li>
    );
  };

  return (
    <div className="flex flex-col gap-4" data-testid="tw-skills">
      <p className="text-sm text-muted-foreground">
        The agent loads a skill’s procedure when a message matches it. Listed here: published skills whose tools and knowledge bases this agent will hold, pinned at the version you choose. Up to {plural(limit, 'skill')}; {count(value.length)} chosen.
      </p>

      {suggestions.length > 0 && (
        <section className="flex flex-col gap-1.5" aria-label="Suggested by the template">
          <h3 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Sparkles className="size-3.5" /> Suggested by the template
          </h3>
          <ul className="divide-y rounded-md border">
            {suggestions.map((s) => {
              const c = candidates.attachable.find((x) => x.skillId === s.skillId);
              return c ? row(c, s.reason) : null;
            })}
            {blockedSuggestions.map((s) => {
              const b = candidates.blocked.find((x) => x.skillId === s.skillId);
              const why = b?.reason ?? 'Not published for this team';
              return (
                <li key={s.skillId} className="flex flex-wrap items-center gap-2 px-3 py-2.5 text-sm" data-testid={`tw-skill-blocked-${s.skillId}`}>
                  <AlertTriangle className="size-3.5 shrink-0 text-warning-text" />
                  <span className="font-medium">{s.name}</span>
                  <span className="text-xs text-muted-foreground">{why}</span>
                  {b?.kind === 'access' && (
                    <Button variant="link" size="sm" className="ml-auto h-auto p-0 text-xs" onClick={onBackToConfigure}>
                      Back to Configure
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section className="flex flex-col gap-1.5" aria-label="Skills this agent can use">
        <h3 className="text-xs font-medium text-muted-foreground">{suggestions.length ? 'Other skills this agent can use' : 'Skills this agent can use'}</h3>
        {rest.length ? (
          <ul className="divide-y rounded-md border">{rest.map((c) => row(c))}</ul>
        ) : (
          <div className="flex flex-col items-center gap-1.5 rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground" data-testid="tw-skills-none">
            <p>
              {candidates.attachable.length ? 'No other published skill fits this agent.' : 'No published skill fits this agent’s tools and knowledge bases yet.'}{' '}
              {otherBlocked.length
                ? `${otherBlocked[0].name} would, but ${otherBlocked[0].reason.replace(/^Needs/, 'it needs')}.`
                : 'Skills can be attached from the agent’s page once a team publishes one that fits.'}
            </p>
            {otherBlocked.length > 0 && (
              <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onBackToConfigure}>
                Back to Configure
              </Button>
            )}
          </div>
        )}
      </section>

      {otherBlocked.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{plural(otherBlocked.length, 'more skill')} {otherBlocked.length === 1 ? 'needs' : 'need'} tools or knowledge this agent will not have</summary>
          <ul className="mt-1.5 flex flex-col gap-1 pl-4">
            {otherBlocked.map((b) => (
              <li key={b.skillId}>
                <span className="text-foreground">{b.name}</span> · {b.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
