'use client';

/**
 * A plugin update's notice and review (c-609), in the app page's "Update available" slot: when the installed plugin
 * version differs from the one the team runs, what taking it would change (each new, changed and removed tool, the
 * team's agents and workflows that use the changed and removed ones, and the version each template copy came from),
 * and one Take the update. Nothing shows while the team runs the installed version or plugin_updates is off.
 */
import * as React from 'react';
import { ArrowUp, Code2 } from 'lucide-react';
import { toast } from 'sonner';

import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type ToolChange,
  usePluginTemplates,
  usePluginUpdate,
  useTakePluginUpdate,
  useToolUses,
} from '@/hooks/plugin-update-queries';
import { plural } from '@/lib/format';

const CHANGE: Record<ToolChange['change'], { label: string; variant: 'default' | 'secondary' | 'destructive' }> = {
  new: { label: 'New', variant: 'secondary' },
  changed: { label: 'Changed', variant: 'default' },
  removed: { label: 'Removed', variant: 'destructive' },
};

/** What changed in one tool, in words: its inputs, then the other fields that changed. */
function changeText(t: ToolChange): string {
  if (t.change === 'new') return t.inputs.added.length ? `Takes ${t.inputs.added.join(', ')}` : 'Takes no inputs';
  if (t.change === 'removed') return 'No longer in the app; calls to it fail once you take the update';
  const parts = [
    t.inputs.added.length ? `adds ${t.inputs.added.join(', ')}` : '',
    t.inputs.removed.length ? `drops ${t.inputs.removed.join(', ')}` : '',
    t.inputs.changed.length ? `changes ${t.inputs.changed.join(', ')}` : '',
    t.changed.length ? `changes its ${t.changed.join(', ').replaceAll('_', ' ')}` : '',
  ].filter(Boolean);
  const said = parts.join('; ');
  return said ? said.charAt(0).toUpperCase() + said.slice(1) : 'Changed';
}

function counts(tools: ToolChange[]): string {
  const n = (c: ToolChange['change']) => tools.filter((t) => t.change === c).length;
  return [n('new') && plural(n('new'), 'new tool'), n('changed') && `${n('changed')} changed`, n('removed') && `${n('removed')} removed`]
    .filter(Boolean)
    .join(', ');
}

export function PluginUpdatePanel({ appId, name }: { appId: string; name: string }) {
  const update = usePluginUpdate(appId);
  const [open, setOpen] = React.useState(false);
  const status = (update.error as { status?: number } | null)?.status;
  // 404: the install has plugin_updates off, or the team has not turned the app on; nothing to show either way.
  if (update.isPending || status === 404) return null;
  if (update.isError)
    return <QueryError what="this app's update" error={update.error} onRetry={() => update.refetch()} retrying={update.isFetching} />;
  const u = update.data;
  if (!u.available) return null;
  return (
    <div className="flex flex-col gap-3" data-testid="app-update">
      <Alert>
        <ArrowUp />
        <AlertTitle>{`Update available: ${counts(u.tools) || 'no tool changes'}`}</AlertTitle>
        <AlertDescription>
          <p>
            Your team runs {name} {u.version ?? 'as first turned on'}; {u.installed.version} is installed. Your agents keep
            calling {u.version ?? 'the current version'} until you take the update.
          </p>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => setOpen((v) => !v)} data-testid="app-update-review">
            {open ? 'Hide the review' : 'Review the update'}
          </Button>
        </AlertDescription>
      </Alert>
      {open && <UpdateReview appId={appId} name={name} tools={u.tools} to={u.installed.version} digest={u.installed.digest} />}
    </div>
  );
}

function UpdateReview({ appId, name, tools, to, digest }: { appId: string; name: string; tools: ToolChange[]; to: string; digest: string }) {
  const touched = tools.filter((t) => t.change !== 'new').map((t) => t.name);
  const uses = useToolUses(touched);
  const copies = usePluginTemplates(appId);
  const take = useTakePluginUpdate(appId);
  const usedBy = (tool: string) => (uses.data?.[tool] ?? []).map((u) => `${u.name} (${u.kind})`);
  const held = (copies.data ?? []).filter((c) => c.installed.copies > 0);
  return (
    <div className="flex flex-col gap-3" data-testid="app-update-details">
      <Section title="Tools" description={`What ${to} changes. New tools stay off for your team until you take the update.`} flush>
        <Rows testId="app-update-tools">
          {tools.map((t) => (
            <Row
              key={t.name}
              wrap
              leading={t.python ? <Code2 className="size-4 text-muted-foreground" aria-label="Python tool" /> : undefined}
              title={
                <span className="flex flex-wrap items-center gap-2">
                  {t.title}
                  <Badge variant={CHANGE[t.change].variant}>{CHANGE[t.change].label}</Badge>
                  <Badge variant="outline">{t.access === 'write' ? 'Writes' : 'Reads'}</Badge>
                </span>
              }
              description={
                <span className="flex flex-col gap-0.5">
                  <span>{changeText(t)}</span>
                  {t.change !== 'new' &&
                    (uses.isPending ? (
                      <Skeleton className="h-3 w-40" />
                    ) : uses.isError ? (
                      <span>Couldn’t check which agents and workflows use it.</span>
                    ) : usedBy(t.name).length ? (
                      <span>Used by {usedBy(t.name).join(', ')}</span>
                    ) : (
                      <span>No agent or workflow in your team uses it.</span>
                    ))}
                  {t.python && <span>A Python tool runs the installed code whichever version your team runs.</span>}
                </span>
              }
            />
          ))}
        </Rows>
      </Section>
      {held.length > 0 && (
        <Section title="Your copies" description="Copies are your team's own; taking the update does not change them." flush>
          <Rows testId="app-update-copies">
            {held.map((c) => (
              <Row
                key={c.id}
                wrap
                title={c.title}
                description={`Made from version ${c.installed.version ?? '?'}${c.installed.changed || c.installed.newerAvailable ? ` · ${name} ${to} brings a newer template` : ' · up to date'}`}
              />
            ))}
          </Rows>
        </Section>
      )}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-4">
        <p className="min-w-0 flex-1 basis-64 text-sm text-muted-foreground">
          Your team’s calls use {to} from the next one. Other teams keep the version they run.
        </p>
        <LoadingButton
          isLoading={take.isPending}
          onClick={() =>
            take.mutate(digest, {
              onSuccess: () => toast.success(`${name} ${to} is now your team’s version`),
              onError: (e) => toast.error('Couldn’t take the update', { description: e.message }),
            })
          }
          data-testid="app-update-take"
        >
          Take the update
        </LoadingButton>
      </div>
    </div>
  );
}
