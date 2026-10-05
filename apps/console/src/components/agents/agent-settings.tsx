'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpRight, BookOpen, Plus, UserCheck, Wrench, X } from 'lucide-react';

import { CHANNEL_ICON } from '@/components/agents/agent-card';
import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { LiveBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { Lookups } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import type { Agent, AgentGuardrails, Channel, Tool, Version } from '@/lib/types/domain';

/** Everything one save of the agent page can change. */
export interface AgentDraft {
  name: string;
  role: string;
  model: string;
  owner: string;
  channels: Channel[];
  instructions: string;
  toolIds: string[];
  collections: string[];
  guardrails: AgentGuardrails;
}

export const draftOf = (a: Agent): AgentDraft => ({
  name: a.name,
  role: a.role,
  model: a.model,
  owner: a.owner,
  channels: a.channels,
  instructions: a.instructions,
  toolIds: a.toolIds,
  collections: a.collections,
  guardrails: a.guardrails,
});

const SECTION: Record<keyof AgentDraft, string> = {
  name: 'Identity',
  role: 'Identity',
  model: 'Identity',
  owner: 'Identity',
  channels: 'Identity',
  instructions: 'Instructions',
  toolIds: 'Tools',
  collections: 'Knowledge',
  guardrails: 'Guardrails',
};

/** Section names whose values differ between the saved agent and the draft. */
export function changedSections(saved: AgentDraft, draft: AgentDraft) {
  const keys = (Object.keys(draft) as (keyof AgentDraft)[]).filter((k) => JSON.stringify(saved[k]) !== JSON.stringify(draft[k]));
  return [...new Set(keys.map((k) => SECTION[k]))];
}

const CHANNEL_LABEL: Record<Channel, string> = { voice: 'Voice', chat: 'Chat', email: 'Email', api: 'API' };

type Set = <K extends keyof AgentDraft>(k: K, v: AgentDraft[K]) => void;

export function IdentitySection({ draft, set, lookups, errors }: { draft: AgentDraft; set: Set; lookups?: Lookups; errors: Partial<Record<'name' | 'role', string>> }) {
  return (
    <SettingsSection title="Identity" description="Reviewers see the name and job on every run this agent pauses.">
      <div className="grid gap-4 md:grid-cols-2">
        <FormField id="ag-name" label="Name" error={errors.name}>
          <Input id="ag-name" value={draft.name} onChange={(e) => set('name', e.target.value)} className="bg-card" aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="ag-owner" label="Owning team">
          <Select value={draft.owner} onValueChange={(v) => set('owner', v)}>
            <SelectTrigger id="ag-owner" className="w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {lookups?.owners.map((o) => (
                <SelectItem key={o} value={o}>
                  {o}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="ag-role" label="Job" error={errors.role} className="md:col-span-2">
          <Input id="ag-role" value={draft.role} onChange={(e) => set('role', e.target.value)} className="bg-card" aria-invalid={!!errors.role} />
        </FormField>
        <FormField id="ag-model" label="Model">
          <Select value={draft.model} onValueChange={(v) => set('model', v)}>
            <SelectTrigger id="ag-model" className="w-full bg-card font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {lookups?.models.map((m) => (
                <SelectItem key={m} value={m} className="font-mono text-xs">
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="ag-channels" label="Can talk on" hint="Where the agent is reachable is set by the deployments of the workflows that use it.">
          <ToggleGroup id="ag-channels" type="multiple" variant="outline" value={draft.channels} onValueChange={(v) => v.length && set('channels', v as Channel[])} className="w-full bg-card">
            {(['voice', 'chat', 'email', 'api'] as Channel[]).map((c) => {
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

export function InstructionsSection({ draft, set }: { draft: AgentDraft; set: Set }) {
  return (
    <SettingsSection title="Instructions" description="What the agent must always and never do.">
      <Textarea
        value={draft.instructions}
        onChange={(e) => set('instructions', e.target.value)}
        className="min-h-56 bg-card font-mono text-[13px] leading-relaxed"
        placeholder="Always cite the policy section behind a decision. Never release funds without a confirmed callback."
        aria-label="Instructions"
      />
      <p className="mt-1.5 text-xs text-muted-foreground tabular-nums">{draft.instructions.length.toLocaleString()} characters</p>
    </SettingsSection>
  );
}

export function ToolsSection({ draft, set, tools, onGrant }: { draft: AgentDraft; set: Set; tools: Tool[]; onGrant: () => void }) {
  const granted = tools.filter((t) => draft.toolIds.includes(t.id));
  return (
    <SettingsSection title={`Tools · ${draft.toolIds.length}`} description="The only systems this agent may call. Tools marked review pause every call for a person.">
      <div className="flex flex-col gap-3">
        {granted.length === 0 ? (
          <p className="text-sm text-muted-foreground">No tools. The agent can only answer from knowledge.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {granted.map((t) => (
              <li key={t.id} className="flex items-center gap-1.5 rounded-md border bg-card py-1 pr-1 pl-2.5 text-sm">
                {t.module && <span className="text-xs text-muted-foreground">{t.module} ·</span>}
                <code className="font-mono text-xs">{t.name}</code>
                {t.access === 'money_movement' && <span className="text-[11px] text-red-600 dark:text-red-400">moves money · four eyes</span>}
                {t.requiresReview && <UserCheck className="size-3.5 text-amber-600" aria-label="Pauses for review" />}
                <Button variant="ghost" size="icon" className="size-6" aria-label={`Remove ${t.name}`} onClick={() => set('toolIds', draft.toolIds.filter((x) => x !== t.id))}>
                  <X className="size-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <Button variant="outline" size="sm" className="self-start bg-card" onClick={onGrant}>
          <Wrench className="size-3.5" /> Grant tools
        </Button>
      </div>
    </SettingsSection>
  );
}

export function KnowledgeSection({ draft, onChoose }: { draft: AgentDraft; onChoose: () => void }) {
  return (
    <SettingsSection title={`Knowledge · ${draft.collections.length}`} description="Collections the agent may search and cite.">
      <div className="flex flex-col gap-3">
        {draft.collections.length === 0 ? (
          <p className="text-sm text-muted-foreground">No collections. The agent cannot cite policy or product documents.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {draft.collections.map((c) => (
              <li key={c} className="flex items-center gap-1.5 rounded-md border bg-card px-2.5 py-1 text-sm">
                <BookOpen className="size-3.5 text-muted-foreground" /> {c}
              </li>
            ))}
          </ul>
        )}
        <Button variant="outline" size="sm" className="self-start bg-card" onClick={onChoose}>
          <BookOpen className="size-3.5" /> Choose collections
        </Button>
      </div>
    </SettingsSection>
  );
}

const UNSURE: Record<AgentGuardrails['whenUnsure'], string> = {
  handoff: 'Hand to a person',
  ask: 'Ask the customer to clarify',
  decline: 'Decline and explain why',
};

export function GuardrailsSection({ draft, set }: { draft: AgentDraft; set: Set }) {
  const g = draft.guardrails;
  const [topic, setTopic] = React.useState('');
  const [topicError, setTopicError] = React.useState<string | null>(null);
  const put = (patch: Partial<AgentGuardrails>) => set('guardrails', { ...g, ...patch });
  const addTopic = () => {
    const t = topic.trim();
    if (!t) return;
    if (g.blockedTopics.some((x) => x.toLowerCase() === t.toLowerCase())) return setTopicError(`“${t}” is already on the list.`);
    put({ blockedTopics: [...g.blockedTopics, t] });
    setTopic('');
  };
  return (
    <SettingsSection title="Guardrails" description="Apply in every workflow that uses this agent; they cannot be left off a canvas.">
      <div className="flex flex-col gap-4">
        <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-3">
          <div>
            <label htmlFor="g-pii" className="text-sm font-medium">
              Redact personal data
            </label>
            <p className="text-xs text-muted-foreground">Account numbers, SINs and card numbers are masked in logs and transcripts.</p>
          </div>
          <Switch id="g-pii" checked={g.redactPii} onCheckedChange={(v) => put({ redactPii: v })} />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <FormField id="g-max" label="Tool calls per turn">
            <Select value={String(g.maxToolCallsPerTurn)} onValueChange={(v) => put({ maxToolCallsPerTurn: Number(v) })}>
              <SelectTrigger id="g-max" className="w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[2, 4, 6, 8, 10].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    At most {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
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
        </div>
        <FormField id="g-topic" label="Topics it must not discuss" optional error={topicError ?? undefined}>
          <div className="flex gap-2">
            <Input
              id="g-topic"
              value={topic}
              onChange={(e) => (setTopic(e.target.value), setTopicError(null))}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addTopic();
                }
              }}
              placeholder="e.g. Tax advice"
              className="bg-card"
            />
            <Button variant="outline" onClick={addTopic} disabled={!topic.trim()} className="bg-card">
              <Plus className="size-4" /> Add
            </Button>
          </div>
          {g.blockedTopics.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {g.blockedTopics.map((t) => (
                <Badge key={t} variant="secondary" className="gap-1 pr-1">
                  {t}
                  <button type="button" aria-label={`Remove ${t}`} onClick={() => put({ blockedTopics: g.blockedTopics.filter((x) => x !== t) })} className="rounded p-0.5 hover:bg-muted">
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}
        </FormField>
      </div>
    </SettingsSection>
  );
}

/** Rail card: where the agent runs, and which agent version each workflow is pinned to. */
export function UsedInCard({ agent, onCreateChat, creating }: { agent: Agent; onCreateChat: () => void; creating: boolean }) {
  const behind = agent.usedIn.filter((u) => u.pinnedVersion < agent.version);
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
          <p className="rounded-md bg-amber-500/10 px-2.5 py-2 text-xs text-amber-800 dark:text-amber-300">
            v{agent.version} reaches production when {behind.length === 1 ? behind[0].workflowName : `${behind.length} workflows`} {behind.length === 1 ? 'is' : 'are'} republished.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function HistoryCard({ versions, loading, onOpen }: { versions?: Version[]; loading: boolean; onOpen: () => void }) {
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
          <ol className="flex flex-col gap-2 text-sm">
            {(versions ?? []).slice(0, 3).map((v) => (
              <li key={v.version} className="flex gap-2">
                <span className="font-mono text-xs leading-5 font-medium">v{v.version}</span>
                <span className="min-w-0">
                  <span className="block truncate">{v.note}</span>
                  <span className="text-xs text-muted-foreground">{relativeTime(v.publishedAt)}</span>
                  {v.evalSummary && <EvalSummaryLine summary={v.evalSummary} className="flex" />}
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
