'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpRight, BookOpen, LayoutTemplate, Plus, Wrench } from 'lucide-react';

import { CHANNEL_ICON } from '@/components/agents/agent-card';
import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { EntityPicker } from '@/components/shared/entity-picker';
import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { Row, Rows } from '@/components/shared/surface';
import { VersionTimeline, VersionTimelineItem } from '@/components/shared/version-history';
import { AgentVersionBadge, LiveBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { guardrailOptions, knowledgeBaseOptions, toolOptions, widgetOptionsFor } from '@/hooks/options-queries';
import { useGuardrails } from '@/hooks/queries';
import type { Lookups } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import type { WidgetPin, WidgetSettings } from '@/lib/types/widgets';
import type { Agent, AgentControls, AgentGuardrails, AgentLimits, AgentPublicKeyOverride, AgentRun, AgentVersion, Channel, GrantableTool, Guardrail, MemorySettings, ModelAlias } from '@/lib/types/domain';

import { modelHint, ModelSelect } from './model-select';
import { teamLabel } from '@/components/shared/team-name';
import { useTeam } from '@/hooks/use-team';

/** Everything one save of the agent page can change. */
export interface AgentDraft {
  name: string;
  role: string;
  model: string;
  channels: Channel[];
  instructions: string;
  toolIds: string[];
  collections: string[];
  guardrails: AgentGuardrails;
  guardrailPins: { guardrailId: string; version: number; enabled: boolean }[];
  limits: AgentLimits;
  /** As the API returns them (name and required tools included); the save sends id and version only. */
  widgetPins: WidgetPin[];
  widgets: WidgetSettings;
  memory: MemorySettings;
}

export const draftOf = (a: Agent): AgentDraft => ({
  name: a.name,
  role: a.role,
  model: a.model,
  channels: a.channels,
  instructions: a.instructions,
  toolIds: a.toolIds,
  collections: a.collections,
  guardrails: a.guardrails,
  guardrailPins: (a.guardrailPins ?? []).map((p) => ({ guardrailId: p.guardrailId, version: p.version, enabled: p.enabled ?? true })),
  limits: a.limits,
  widgetPins: a.widgetPins ?? [],
  widgets: a.widgets ?? { compose: false, perTurn: null },
  memory: a.memory ?? { enabled: true, kinds: ['fact', 'preference', 'episode'] },
});

/**
 * Keeps the limits in step with the version they are saved on, as agents-service requires: the agent's model is the
 * default and allowed, its knowledge bases are allowed, and only granted tools may be switched off.
 */
export function followLimits(d: AgentDraft): AgentDraft {
  const l = d.limits;
  const limits: AgentLimits = {
    ...l,
    defaultModel: d.model,
    allowedModels: l.allowedModels.includes(d.model) ? l.allowedModels : [d.model, ...l.allowedModels.filter((m) => m !== l.defaultModel)],
    allowedKnowledgeBaseIds: [...new Set([...d.collections, ...l.allowedKnowledgeBaseIds])],
    switchableToolIds: l.switchableToolIds.filter((t) => d.toolIds.includes(t)),
    ...(l.switchableWidgetIds ? { switchableWidgetIds: l.switchableWidgetIds.filter((w) => d.widgetPins.some((p) => p.widgetId === w)) } : {}),
  };
  return JSON.stringify(limits) === JSON.stringify(l) ? d : { ...d, limits };
}

const SECTION: Record<keyof AgentDraft, string> = {
  name: 'Identity',
  role: 'Identity',
  model: 'Identity',
  channels: 'Identity',
  instructions: 'Instructions',
  toolIds: 'Tools',
  collections: 'Knowledge',
  guardrails: 'Guardrails',
  guardrailPins: 'Guardrails',
  limits: 'Caller limits',
  widgetPins: 'Widgets',
  widgets: 'Widgets',
  memory: 'Memory',
};

/** Section names whose values differ between the saved agent and the draft. */
export function changedSections(saved: AgentDraft, draft: AgentDraft) {
  const keys = (Object.keys(draft) as (keyof AgentDraft)[]).filter((k) => JSON.stringify(saved[k]) !== JSON.stringify(draft[k]));
  return [...new Set(keys.map((k) => SECTION[k]))];
}

const CHANNEL_LABEL: Record<Channel, string> = { voice: 'Voice', chat: 'Chat', email: 'Email', api: 'API' };

type Set = <K extends keyof AgentDraft>(k: K, v: AgentDraft[K]) => void;

/** `models` are the aliases publish accepts; an agent saved on any other alias still shows it, marked, so it can be changed. */
/** `channels` are the ones the runtime serves (`Agent.controls`); no other is offered. */
export function IdentitySection({ draft, set, teamId, models, errors, channels }: { draft: AgentDraft; set: Set; teamId: string | null; models: ModelAlias[]; errors: Partial<Record<'name' | 'role', string>>; channels: Channel[] }) {
  const { teams } = useTeam();
  return (
    <SettingsSection title="Identity" description="Reviewers see the name and job on every run this agent pauses.">
      <div className="grid gap-4 md:grid-cols-2">
        <FormField id="ag-name" label="Name" error={errors.name}>
          <Input id="ag-name" value={draft.name} onChange={(e) => set('name', e.target.value)} className="bg-card" aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="ag-owner" label="Owning team" hint="The team that created the agent. It cannot be moved to another team.">
          <Input id="ag-owner" value={teamLabel(teamId, teams)} readOnly disabled className="bg-card" />
        </FormField>
        <FormField id="ag-role" label="Job" error={errors.role} className="md:col-span-2">
          <Input id="ag-role" value={draft.role} onChange={(e) => set('role', e.target.value)} className="bg-card" aria-invalid={!!errors.role} />
        </FormField>
        <FormField id="ag-model" label="Model" hint={modelHint(models, draft.model)}>
          <ModelSelect id="ag-model" value={draft.model} onValueChange={(v) => set('model', v)} aliases={models} className="bg-card" />
        </FormField>
        <FormField id="ag-channels" label="Can talk on" hint="Where the agent is reachable is set by the deployments of the workflows that use it.">
          <ToggleGroup id="ag-channels" type="multiple" variant="outline" value={draft.channels.filter((c) => channels.includes(c))} onValueChange={(v) => v.length && set('channels', v as Channel[])} className="w-full bg-card">
            {channels.map((c) => {
              const Icon = CHANNEL_ICON[c];
              return (
                <ToggleGroupItem key={c} value={c} className="flex-1" aria-label={CHANNEL_LABEL[c]}>
                  <Icon className="size-3.5" /> {CHANNEL_LABEL[c]}
                </ToggleGroupItem>
              );
            })}
          </ToggleGroup>
        </FormField>
      </div>
    </SettingsSection>
  );
}

/** `toolbar` holds the prompt builder and "Attach always-on skill"; `footer` lists the always-on skills that add to every turn. */
export function InstructionsSection({ draft, set, toolbar, footer, textareaRef }: { draft: AgentDraft; set: Set; toolbar?: React.ReactNode; footer?: React.ReactNode; textareaRef?: React.Ref<HTMLTextAreaElement> }) {
  return (
    <SettingsSection title="Instructions" description="What the agent must always and never do.">
      {toolbar && <div className="mb-2 flex flex-wrap justify-end gap-2">{toolbar}</div>}
      <Textarea
        ref={textareaRef}
        value={draft.instructions}
        onChange={(e) => set('instructions', e.target.value)}
        className="min-h-56 bg-card font-mono text-[13px] leading-relaxed"
        placeholder="Always cite the policy section behind a decision. Never release funds without a confirmed callback."
        aria-label="Instructions"
      />
      <p className="mt-1.5 text-xs text-muted-foreground tabular-nums">{draft.instructions.length.toLocaleString()} characters</p>
      {footer && <div className="mt-2">{footer}</div>}
    </SettingsSection>
  );
}

/**
 * The tools the agent may call, picked through the tools options route so any grantable tool can be found (c-135).
 * Grants the registry no longer offers (unpublished, hidden or removed from their module) are listed apart with
 * Remove, as c-048 asks, rather than as a chip the picker cannot label.
 */
export function ToolsSection({ draft, set, stale = [] }: { draft: AgentDraft; set: Set; stale?: string[] }) {
  const gone = stale.filter((id) => draft.toolIds.includes(id));
  const offered = draft.toolIds.filter((id) => !gone.includes(id));
  return (
    <SettingsSection title={`Tools · ${draft.toolIds.length}`} description="The only systems this agent may call. Tools marked review pause every call for a person.">
      <div className="flex flex-col gap-3">
        {draft.toolIds.length === 0 && <p className="text-sm text-muted-foreground">No tools. The agent can only answer from knowledge.</p>}
        <EntityPicker source={toolOptions} value={offered} onChange={(ids) => set('toolIds', [...ids, ...gone])} addLabel="Grant tools" searchPlaceholder="Search tools by name or system…" emptyText="No tool matches." icon={Wrench} testId="agent-tools-picker" />
        {gone.length > 0 && (
          <div className="flex flex-col gap-1" data-testid="stale-grants">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">No longer offered</p>
            <Rows className="rounded-lg border border-warning/40">
              {gone.map((id) => (
                <Row
                  key={id}
                  title={<code className="font-mono text-sm">{id}</code>}
                  description="Unpublished, hidden or removed from its module. Saving drops it."
                  trailing={
                    <Button type="button" variant="outline" size="sm" onClick={() => set('toolIds', draft.toolIds.filter((x) => x !== id))} aria-label={`Remove ${id}`}>
                      Remove
                    </Button>
                  }
                />
              ))}
            </Rows>
          </div>
        )}
      </div>
    </SettingsSection>
  );
}

/** The knowledge bases the agent may search and cite, stored by id and picked through the options route (c-135). */
export function KnowledgeSection({ draft, set }: { draft: AgentDraft; set: Set }) {
  return (
    <SettingsSection title={`Knowledge · ${draft.collections.length}`} description="Knowledge bases the agent may search and cite.">
      {draft.collections.length === 0 && <p className="mb-2 text-sm text-muted-foreground">No knowledge bases. The agent cannot cite policy or product documents.</p>}
      <EntityPicker source={knowledgeBaseOptions} value={draft.collections} onChange={(ids) => set('collections', ids)} addLabel="Choose knowledge bases" searchPlaceholder="Search knowledge bases…" emptyText="No knowledge base matches." icon={BookOpen} testId="agent-knowledge-picker" />
    </SettingsSection>
  );
}

/** Widgets the agent may show in chat (c-082): pinned templates by version, composition and a per-answer cap. */
export function WidgetsSection({ draft, set }: { draft: AgentDraft; set: Set }) {
  // A new pin takes the published version on save (version 0 is sent as none); a held pin keeps its version.
  const choose = (ids: string[]) => set('widgetPins', ids.map((id) => draft.widgetPins.find((p) => p.widgetId === id) ?? { widgetId: id, version: 0, name: id }));
  return (
    <SettingsSection title={`Widgets · ${draft.widgetPins.length}`} description="Widgets the agent may fill in a chat answer, and whether it may lay out its own from the approved building blocks.">
      <div className="flex flex-col gap-4">
        {draft.widgetPins.length === 0 && <p className="text-sm text-muted-foreground">No widgets. The agent answers with text, tables and charts only.</p>}
        <EntityPicker source={widgetOptionsFor(draft.toolIds)} value={draft.widgetPins.map((p) => p.widgetId)} onChange={choose} addLabel="Choose widgets" searchPlaceholder="Search widgets…" emptyText="No published widget matches." icon={LayoutTemplate} testId="agent-widget-pins" />
        <div className="flex items-center justify-between gap-4 rounded-md border bg-card px-3 py-2.5">
          <div>
            <Label htmlFor="widgets-compose">Lay out its own widgets</Label>
            <p className="text-xs text-muted-foreground">Built only from the approved building blocks, checked before anything is shown, and marked as composed by the agent.</p>
          </div>
          <Switch id="widgets-compose" checked={draft.widgets.compose} onCheckedChange={(v) => set('widgets', { ...draft.widgets, compose: v })} />
        </div>
        <FormField id="widgets-per-turn" label="Widgets per answer" optional hint="Leave empty for no limit.">
          <Input
            id="widgets-per-turn"
            type="number"
            min={1}
            className="w-32"
            value={draft.widgets.perTurn ?? ''}
            placeholder="e.g. 3"
            onChange={(e) => set('widgets', { ...draft.widgets, perTurn: e.target.value === '' ? null : Math.max(1, Number(e.target.value)) })}
          />
        </FormField>
      </div>
    </SettingsSection>
  );
}

const UNSURE: Record<AgentGuardrails['whenUnsure'], string> = {
  handoff: 'Hand to a person',
  ask: 'Ask the customer to clarify',
  decline: 'Decline and explain why',
};

/** A cap as a number field: empty is no cap, so a real agent is not held to a small menu of choices. */
function CapField({ id, label, value, onChange, hint, placeholder, decimal }: { id: string; label: string; value: number | null; onChange: (v: number | null) => void; hint: string; placeholder: string; decimal?: boolean }) {
  // A cost cap takes cents; a count cap is a whole number of at least one.
  const parse = (raw: string) => (decimal ? Math.max(0.01, Math.round(Number(raw) * 100) / 100) : Math.max(1, Math.floor(Number(raw))));
  return (
    <FormField id={id} label={label} hint={hint}>
      <Input
        id={id}
        type="number"
        min={decimal ? 0.01 : 1}
        step={decimal ? 0.01 : 1}
        inputMode={decimal ? 'decimal' : 'numeric'}
        placeholder={placeholder}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value.trim() === '' ? null : parse(e.target.value))}
        className="bg-card"
      />
    </FormField>
  );
}

/** `shown` are the settings a turn acts on (`Agent.controls.guardrails`); the page offers no other. */
export function GuardrailsSection({ draft, set, shown }: { draft: AgentDraft; set: Set; shown: AgentControls['guardrails'] }) {
  const g = draft.guardrails;
  const library = useGuardrails();
  const put = (patch: Partial<AgentGuardrails>) => set('guardrails', { ...g, ...patch });
  const pinned = new Map(draft.guardrailPins.map((p) => [p.guardrailId, p.version]));
  const off = new Set(draft.guardrailPins.filter((p) => !p.enabled).map((p) => p.guardrailId));
  // Off is saved on the version and goes live with it; the guardrail stays pinned but is not checked.
  const setEnabled = (x: Guardrail, enabled: boolean) => set('guardrailPins', draft.guardrailPins.map((p) => (p.guardrailId === x.id ? { ...p, enabled } : p)));
  // A pin keeps its version; a new pin takes the published one. Deprecated guardrails take no new pins.
  // The picker adds and removes pins (searched on the server, c-136); the rows below are the pinned ones, with their
  // version and on/off. A new pin takes the published version on save (version 0 is sent as none).
  const choices = (library.data ?? []).filter((x) => pinned.has(x.id));
  const choose = (ids: string[]) =>
    set('guardrailPins', ids.map((id) => draft.guardrailPins.find((p) => p.guardrailId === id) ?? { guardrailId: id, version: 0, enabled: true }));
  // Any published version may be pinned; the guardrail's own page lists them all.
  const published = (x: Guardrail) => (x.versions ?? []).filter((v) => v.state === 'published').map((v) => v.version);
  const pinVersion = (x: Guardrail, version: number) => set('guardrailPins', draft.guardrailPins.map((p) => (p.guardrailId === x.id ? { ...p, version } : p)));
  return (
    <SettingsSection title="Guardrails" description="Saved with the agent version. Chat uses the published version; a workflow keeps the version it was published with until it is republished.">
      <div className="flex flex-col gap-4">
        <FormField id="g-topics" label="Blocked topics" hint="Checked on the question and on the answer. A question on a blocked topic gets the guardrail's message instead of an answer. While a guardrail is pinned, answers are checked before they are shown, so they arrive whole instead of streaming.">
          <EntityPicker source={guardrailOptions} value={draft.guardrailPins.map((p) => p.guardrailId)} onChange={choose} addLabel="Pin guardrails" searchPlaceholder="Search guardrails…" emptyText="No published guardrail matches." testId="guardrail-picker" />
          {choices.length === 0 ? null : (
            <div className="flex flex-col gap-2">
              {choices.map((x) => {
                const version = pinned.get(x.id);
                return (
                  // A div, not a label: a label would pass a click on the on/off switch to the pin checkbox.
                  <div key={x.id} className="flex items-start gap-3 rounded-lg border bg-card p-3" data-testid="guardrail-pin">
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                        <Link href={`/guardrails/${x.id}`} className="underline-offset-2 hover:underline" data-testid="guardrail-pin-link">
                          {x.name}
                        </Link>
                        {version !== undefined && published(x).length > 1 ? (
                          <Select value={String(version)} onValueChange={(v) => pinVersion(x, Number(v))}>
                            <SelectTrigger className="h-7 w-24 text-xs" aria-label={`${x.name} version`}>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {published(x).map((n) => (
                                <SelectItem key={n} value={String(n)}>
                                  v{n}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <span className="text-xs font-normal text-muted-foreground">v{version || x.publishedVersion}</span>
                        )}
                        {version !== undefined && (off.has(x.id) ? <Badge variant="outline" className="border-warning/50 text-warning-text" data-testid="guardrail-off">Off · not checked</Badge> : <Badge variant="secondary">Enforced</Badge>)}
                        {x.status === 'deprecated' && <Badge variant="outline">Deprecated</Badge>}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {x.config.topics.map((t) => (
                          <Badge key={t} variant="outline" className="font-normal">
                            {t}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    {version !== undefined && (
                      <Switch checked={!off.has(x.id)} onCheckedChange={(v) => setEnabled(x, v)} aria-label={`Check ${x.name}`} className="mt-0.5" />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </FormField>
        {shown.includes('redactPii') && (
          <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-3">
            <div>
              <label htmlFor="g-pii" className="text-sm font-medium">
                Redact personal data
              </label>
              <p className="text-xs text-muted-foreground">SSNs, card and account numbers, emails and phones are masked in replies, stored messages and tool results people see. The agent still reads the real values.</p>
            </div>
            <Switch id="g-pii" checked={g.redactPii} onCheckedChange={(v) => put({ redactPii: v })} />
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          {shown.includes('maxToolCallsPerTurn') && <CapField id="g-max" label="Tool calls per turn" value={g.maxToolCallsPerTurn} onChange={(v) => put({ maxToolCallsPerTurn: v })} hint="Empty means no cap; the model-call cap still bounds the turn." placeholder="No cap" />}
          {shown.includes('maxModelCallsPerTurn') && <CapField id="g-model-calls" label="Model calls per turn" value={g.maxModelCallsPerTurn ?? null} onChange={(v) => put({ maxModelCallsPerTurn: v })} hint="Empty means the platform default, 50." placeholder="50" />}
          {shown.includes('maxModelCallsPerConversation') && <CapField id="g-conversation-calls" label="Model calls per conversation" value={g.maxModelCallsPerConversation ?? null} onChange={(v) => put({ maxModelCallsPerConversation: v })} hint="When a chat reaches it, the chat pauses until its owner continues. Empty means the platform default, 200." placeholder="200" />}
          {shown.includes('maxCostPerConversation') && <CapField id="g-conversation-cost" label="Cost per conversation" value={g.maxCostPerConversation ?? null} onChange={(v) => put({ maxCostPerConversation: v })} hint="In the price table’s currency. Empty means the platform default, 5.00." placeholder="5.00" decimal />}
          {shown.includes('whenUnsure') && (
          <FormField id="g-unsure" label="When unsure">
            <Select value={g.whenUnsure} onValueChange={(v) => put({ whenUnsure: v as AgentGuardrails['whenUnsure'] })}>
              <SelectTrigger id="g-unsure" className="w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(UNSURE).map(([v, l]) => (
                  <SelectItem key={v} value={v}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          )}
        </div>
      </div>
    </SettingsSection>
  );
}

const PUBLIC_KEY: Record<AgentPublicKeyOverride, string> = {
  tools: 'Switch tools off',
  knowledge: 'Narrow knowledge',
  budget: 'Lower the budget',
  outputSchema: 'Set an output schema',
  variables: 'Set variables',
};

const num = (v: string) => (v.trim() === '' ? Number.NaN : Number(v));

/**
 * What callers may change when they use this agent: a banker in chat, a service through the API, a widget on a public
 * key. Saved with the version and approved in its publish review; anything outside these is refused, never adjusted.
 */
export function LimitsSection({ draft, set, models, tools }: { draft: AgentDraft; set: Set; models: ModelAlias[]; tools: GrantableTool[] }) {
  const l = draft.limits;
  const put = (patch: Partial<AgentLimits>) => set('limits', { ...l, ...patch });
  const toggle = <T,>(list: T[], x: T, on: boolean) => (on ? [...list, x] : list.filter((y) => y !== x));
  const modelNames = [...new Set([draft.model, ...models.map((m) => m.name), ...l.allowedModels])].filter(Boolean);
  const granted = tools.filter((t) => draft.toolIds.includes(t.id));
  const t = l.temperature;
  const b = l.budget;
  return (
    <div data-testid="agent-limits">
    <SettingsSection title="Caller limits" description="What callers may change when they use this agent. Published with the version through its review; a request outside them is refused.">
      <div className="flex flex-col gap-4">
        <FormField id="lim-models" label="Models callers may choose" hint={`The default is the agent's model, ${draft.model || 'the runtime model'}.`}>
          <div className="flex flex-col gap-2">
            {modelNames.map((m) => (
              <label key={m} className="flex items-center gap-2 text-sm">
                <Checkbox checked={l.allowedModels.includes(m)} disabled={m === draft.model} onCheckedChange={(v) => put({ allowedModels: toggle(l.allowedModels, m, v === true) })} aria-label={`Allow ${m}`} />
                <code className="font-mono text-xs">{m}</code>
                {m === draft.model && <Badge variant="secondary">Default</Badge>}
              </label>
            ))}
          </div>
        </FormField>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
            <label className="flex items-center justify-between gap-3 text-sm font-medium" htmlFor="lim-temp">
              Callers may set temperature
              <Switch id="lim-temp" checked={!!t} onCheckedChange={(on) => put({ temperature: on ? { min: 0, max: 1, default: 0.3 } : undefined })} />
            </label>
            {t && (
              <div className="grid grid-cols-3 gap-2">
                {(['min', 'default', 'max'] as const).map((k) => (
                  <FormField key={k} id={`lim-temp-${k}`} label={k === 'default' ? 'Default' : k === 'min' ? 'Lowest' : 'Highest'}>
                    <Input id={`lim-temp-${k}`} type="number" step="0.1" min={0} max={2} value={Number.isNaN(t[k]) ? '' : t[k]} onChange={(e) => put({ temperature: { ...t, [k]: num(e.target.value) } })} className="bg-background" />
                  </FormField>
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
            <label className="flex items-center justify-between gap-3 text-sm font-medium" htmlFor="lim-budget">
              Budget per run
              <Switch id="lim-budget" checked={!!b} onCheckedChange={(on) => put({ budget: on ? { ceilingUsd: 1, defaultUsd: 0.25 } : undefined })} />
            </label>
            {b && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <FormField id="lim-budget-default" label="Default (USD)">
                  <Input id="lim-budget-default" type="number" step="0.05" min={0} value={Number.isNaN(b.defaultUsd) ? '' : b.defaultUsd} onChange={(e) => put({ budget: { ...b, defaultUsd: num(e.target.value) } })} className="bg-background" />
                </FormField>
                <FormField id="lim-budget-ceiling" label="Ceiling (USD)" hint="Callers may only lower it.">
                  <Input id="lim-budget-ceiling" type="number" step="0.05" min={0} value={Number.isNaN(b.ceilingUsd) ? '' : b.ceilingUsd} onChange={(e) => put({ budget: { ...b, ceilingUsd: num(e.target.value) } })} className="bg-background" />
                </FormField>
              </div>
            )}
          </div>
        </div>
        <FormField id="lim-kb" label="Knowledge callers may choose from" hint="The agent's own knowledge is always allowed.">
          {/* The agent's own bases stay allowed: followLimits adds them back whatever is removed here. */}
          <EntityPicker source={knowledgeBaseOptions} value={l.allowedKnowledgeBaseIds} onChange={(ids) => put({ allowedKnowledgeBaseIds: [...new Set([...draft.collections, ...ids])] })} addLabel="Allow knowledge bases" searchPlaceholder="Search knowledge bases…" emptyText="No knowledge base matches." icon={BookOpen} testId="agent-limits-knowledge-picker" />
        </FormField>
        <FormField id="lim-tools" label="Tools callers may switch off" hint="Callers never add a tool.">
          {granted.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tools granted.</p>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {granted.map((x) => (
                <label key={x.id} className="flex items-center gap-2 text-sm">
                  <Checkbox checked={l.switchableToolIds.includes(x.id)} onCheckedChange={(v) => put({ switchableToolIds: toggle(l.switchableToolIds, x.id, v === true) })} aria-label={`Callers may switch off ${x.name}`} />
                  <code className="font-mono text-xs">{x.name}</code>
                </label>
              ))}
            </div>
          )}
        </FormField>
        <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-3">
          <div>
            <label htmlFor="lim-instr" className="text-sm font-medium">
              Callers may add instructions
            </label>
            <p className="text-xs text-muted-foreground">Added after the agent's instructions; never replaces them.</p>
          </div>
          <Switch id="lim-instr" checked={l.callersMayAddInstructions} onCheckedChange={(v) => put({ callersMayAddInstructions: v })} />
        </div>
        <FormField id="lim-public" label="A public widget key may" hint="Model, temperature and instructions are never open to a public key.">
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {(Object.keys(PUBLIC_KEY) as AgentPublicKeyOverride[]).map((k) => (
              <label key={k} className="flex items-center gap-2 text-sm">
                <Checkbox checked={l.publicKeyMay.includes(k)} onCheckedChange={(v) => put({ publicKeyMay: toggle(l.publicKeyMay, k, v === true) })} aria-label={`Public key may ${PUBLIC_KEY[k].toLowerCase()}`} />
                {PUBLIC_KEY[k]}
              </label>
            ))}
          </div>
        </FormField>
      </div>
    </SettingsSection>
    </div>
  );
}

/** Rail card: the agent's newest chats and runs, from agents-service. */
export function RecentRunsCard({ runs, loading }: { runs?: AgentRun[]; loading: boolean }) {
  return (
    <Card className="gap-3 py-4" data-testid="recent-runs-card">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">Recent runs</CardTitle>
      </CardHeader>
      <CardContent className="px-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !runs?.length ? (
          <p className="text-sm text-muted-foreground">No runs yet. Chats with the agent and runs of its workflow appear here.</p>
        ) : (
          <ol className="flex flex-col gap-2 text-sm">
            {runs.map((r) => (
              <li key={r.threadId} className="flex flex-col">
                <span className="truncate font-medium">{r.title || (r.kind === 'chat' ? 'Chat' : 'Workflow run')}</span>
                <span className="text-xs text-muted-foreground">
                  {r.kind === 'chat' ? 'Chat' : 'Run'} · {r.status}
                  {r.version !== undefined && ` · v${r.version}`} · {relativeTime(r.startedAt)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

/** Rail card: where the agent runs, and which agent version each workflow is pinned to. */
export function UsedInCard({ agent, onCreateChat, creating }: { agent: Agent; onCreateChat: () => void; creating: boolean }) {
  // Its own one-step workflow publishes with the agent, so it is never behind.
  const behind = agent.usedIn.filter((u) => !u.own && u.pinnedVersion < agent.version);
  return (
    <Card className="gap-3 py-4" data-testid="used-in-card">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">Used in workflows</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-4">
        {agent.usedIn.length === 0 ? (
          <>
            <p className="text-sm text-muted-foreground">Not in any workflow, so nothing can reach it yet.</p>
            <Button size="sm" variant="outline" onClick={onCreateChat} disabled={creating} className="self-start">
              <Plus className="size-3.5" /> Create chat workflow
            </Button>
          </>
        ) : (
          <ul className="flex flex-col gap-2">
            {agent.usedIn.map((u) => (
              <li key={u.workflowId}>
                <Link href={`/workflows/${u.workflowId}`} className="group flex items-center justify-between gap-2 rounded-md border px-2.5 py-2 text-sm hover:bg-muted/40">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{u.workflowName}</span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      <LiveBadge status={u.status} /> uses v{u.pinnedVersion}
                    </span>
                  </span>
                  <ArrowUpRight className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        )}
        {behind.length > 0 && (
          <p className="rounded-md bg-warning/10 px-2.5 py-2 text-xs text-warning-text">
            v{agent.version} reaches production when {behind.length === 1 ? behind[0].workflowName : `${behind.length} workflows`} {behind.length === 1 ? 'is' : 'are'} republished.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function HistoryCard({ versions, loading, onOpen }: { versions?: AgentVersion[]; loading: boolean; onOpen: () => void }) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="text-sm">History</CardTitle>
        <CardAction>
          <Button variant="ghost" size="sm" className="h-7" onClick={onOpen}>
            All versions
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="px-4">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <VersionTimeline compact>
            {(versions ?? []).slice(0, 3).map((v) => (
              <VersionTimelineItem key={v.version} compact dot={v.current ? 'current' : 'muted'}>
                <div className="flex min-w-0 items-center gap-1.5 text-sm">
                  <span className="font-mono text-xs font-medium">v{v.version}</span>
                  {/* w-0 keeps the note's full width out of the rail's min-content, which would push the rail past a phone's width. */}
                  <span className="w-0 flex-1 truncate">{v.note}</span>
                  <AgentVersionBadge state={v.state} />
                </div>
                <span className="text-xs text-muted-foreground">{relativeTime(v.savedAt)}</span>
                {v.evalSummary && <EvalSummaryLine summary={v.evalSummary} className="flex" />}
              </VersionTimelineItem>
            ))}
          </VersionTimeline>
        )}
      </CardContent>
    </Card>
  );
}
