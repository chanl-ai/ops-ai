'use client';

import * as React from 'react';
import { AlertCircle, CheckCircle2, Info, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useNotificationSettings, useSaveNotifications } from '@/hooks/settings-queries';
import { useTeam } from '@/hooks/use-team';
import { relativeTime } from '@/lib/format';
import type { NotificationEvent } from '@/lib/types/settings';

type Draft = Record<NotificationEvent, string[]>;

export default function NotificationsPage() {
  const { team } = useTeam();
  const query = useNotificationSettings();
  const save = useSaveNotifications();
  const s = query.data;
  const saved = React.useMemo(() => (s ? (Object.fromEntries(s.rules.map((r) => [r.event, r.channelIds])) as Draft) : null), [s]);
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [conflict, setConflict] = React.useState<string | null>(null);
  React.useEffect(() => {
    setDraft(saved);
  }, [saved]);

  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  const toggle = (event: NotificationEvent, channel: string, on: boolean) => setDraft((d) => d && { ...d, [event]: on ? [...d[event], channel] : d[event].filter((c) => c !== channel) });
  const actionable = s?.channels.filter((c) => c.actionable && c.connected).map((c) => c.name) ?? [];

  const submit = async () => {
    if (!s || !draft) return;
    try {
      const next = await save.mutateAsync({ version: s.version, rules: s.rules.map((r) => ({ event: r.event, channelIds: draft[r.event] })) });
      setConflict(null);
      toast.success(`Saved as version ${next.version}`);
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 409) setConflict((e as Error).message);
      else toast.error('Couldn’t save notifications', { description: (e as Error).message });
    }
  };

  return (
    <SettingsPageLayout section="Notifications" description={`Where ${team?.name ?? 'this team'} hears about work that needs a person.`}>
      {query.isPending ? (
        <NotificationsSkeleton />
      ) : query.isError && !s ? (
        <QueryError what="notification settings" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : s && draft ? (
        <div className="flex flex-col gap-4">
          <Alert>
            <Info />
            <AlertDescription>
              Approvals can be approved or rejected from {actionable.filter((n) => n !== 'In Ops AI').join(' and ') || 'other channels'} as well as in Ops AI. The same approval rules and four-eyes checks apply wherever the decision is made.
            </AlertDescription>
          </Alert>

          {conflict && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
                {conflict}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    setConflict(null);
                    await query.refetch();
                  }}
                >
                  Reload
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <Section title="Routing" description={`Version ${s.version} · saved by ${s.updatedBy} ${relativeTime(s.updatedAt)}`} flush>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="min-w-56">Event</TableHead>
                    {s.channels.map((c) => (
                      <TableHead key={c.id} className="text-center whitespace-nowrap">
                        {c.name}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {s.rules.map((r) => (
                    <TableRow key={r.event}>
                      <TableCell className="whitespace-normal">
                        <div className="font-medium">{r.label}</div>
                        <div className="text-xs text-muted-foreground">{r.description}</div>
                      </TableCell>
                      {s.channels.map((c) => (
                        <TableCell key={c.id} className="text-center">
                          <Checkbox
                            aria-label={`${r.label} via ${c.name}`}
                            checked={draft[r.event].includes(c.id)}
                            disabled={!c.connected}
                            onCheckedChange={(v) => toggle(r.event, c.id, !!v)}
                          />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Section>

          <Section title="Channels" description="Channels are connected by a Platform admin; each team picks where its notifications go." flush>
            <ul className="divide-y">
              {s.channels.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{c.name}</div>
                    <div className="truncate text-xs text-muted-foreground">{c.detail}</div>
                  </div>
                  {c.actionable && c.connected && (
                    <Badge variant="outline" className="font-normal">
                      <CheckCircle2 className="text-emerald-600" /> Can approve here
                    </Badge>
                  )}
                  <Badge variant={c.connected ? 'secondary' : 'outline'} className="font-normal">
                    {c.connected ? 'Connected' : 'Not connected'}
                  </Badge>
                </li>
              ))}
            </ul>
          </Section>

          {dirty && (
            <div data-unsaved-bar className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur">
              <span className="text-sm text-muted-foreground">Unsaved changes</span>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setDraft(saved)} disabled={save.isPending}>
                  <RotateCcw className="size-3.5" /> Discard
                </Button>
                <LoadingButton size="sm" isLoading={save.isPending} onClick={submit}>
                  Save changes
                </LoadingButton>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </SettingsPageLayout>
  );
}

/** Same shape as the loaded form: the approvals note, the routing grid and the channel list. */
function NotificationsSkeleton() {
  return (
    <div className="flex flex-col gap-4" data-testid="page-skeleton">
      <Skeleton className="h-14 w-full rounded-lg" />
      <Section title="Routing" flush>
        <div className="flex items-center gap-4 border-b px-4 py-3">
          <Skeleton className="h-4 w-56" />
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="ml-auto h-4 w-14" />
          ))}
        </div>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center gap-4 border-b px-4 py-3 last:border-0">
            <div className="flex w-56 flex-col gap-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-52" />
            </div>
            {[0, 1, 2].map((j) => (
              <Skeleton key={j} className="ml-auto size-4" />
            ))}
          </div>
        ))}
      </Section>
      <Section title="Channels" description="Channels are connected by a Platform admin; each team picks where its notifications go." flush>
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-3 border-b px-4 py-3 last:border-0">
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-56" />
            </div>
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
        ))}
      </Section>
    </div>
  );
}
