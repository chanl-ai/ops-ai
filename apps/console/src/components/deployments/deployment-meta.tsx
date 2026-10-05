'use client';

import { Code2, Mail, MessageSquare } from 'lucide-react';

import { CopyButton } from '@/components/shared/copy-button';
import { Button } from '@/components/ui/button';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { DeployChannel, Deployment, DeployEnvironment } from '@/lib/types/domain';

export const CHANNELS: Record<DeployChannel, { label: string; description: string; icon: typeof Mail }> = {
  widget: { label: 'Chat widget', description: 'Embed on a website; customers chat with the workflow', icon: MessageSquare },
  api: { label: 'API', description: 'Your systems call the workflow over HTTPS', icon: Code2 },
  email: { label: 'Mailbox', description: 'A shared mailbox; each email opens a case with drafted actions', icon: Mail },
};

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

export function ChannelBadge({ channel }: { channel: DeployChannel }) {
  const c = CHANNELS[channel];
  return (
    <span className="inline-flex items-center gap-1.5 text-sm whitespace-nowrap">
      <c.icon className="size-3.5 text-muted-foreground" /> {c.label}
    </span>
  );
}

export function EnvironmentBadge({ environment }: { environment: DeployEnvironment }) {
  return (
    <span className={cn(pill, environment === 'production' ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border bg-muted text-muted-foreground')}>
      {environment === 'production' ? 'Production' : 'Staging'}
    </span>
  );
}

type MailSync = NonNullable<NonNullable<Deployment['email']>['sync']>;

/** Status of a deployment. An active mailbox that is not reading mail says so instead of "Active". */
export function DeploymentStatusBadge({ status, sync }: { status: Deployment['status']; sync?: MailSync }) {
  const s =
    status !== 'active'
      ? { label: 'Paused', cls: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300', dot: 'bg-amber-500' }
      : sync?.status === 'error'
        ? { label: 'Not reading mail', cls: 'border-destructive/30 bg-destructive/10 text-destructive', dot: 'bg-destructive' }
        : sync?.status === 'syncing'
          ? { label: 'Syncing mail', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300', dot: 'bg-sky-500' }
          : { label: 'Active', cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300', dot: 'bg-emerald-500' };
  return (
    <span className={cn(pill, s.cls)} title={sync?.status === 'error' ? 'Reconnect needed' : undefined}>
      <span className={cn('size-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}

/** Headline and detail for the mailbox sync line; while syncing, the detail never claims recent mail as current. */
function syncText(sync: MailSync): { title: string; detail: string } {
  if (sync.status === 'error') return { title: 'Not reading mail', detail: sync.error ?? 'Reconnect needed' };
  if (sync.status === 'syncing')
    return sync.lastMessageAt
      ? { title: 'Catching up', detail: `Reading mail received since ${relativeTime(sync.lastMessageAt)}` }
      : { title: 'First sync running', detail: 'Reading the mailbox for the first time' };
  return { title: 'Reading mail', detail: sync.lastMessageAt ? `Last email ${relativeTime(sync.lastMessageAt)} · ${sync.messages24h} in 24 h` : 'No mail yet' };
}

export function VersionCell({ d }: { d: Pick<Deployment, 'version' | 'latestVersion'> }) {
  const behind = d.latestVersion - d.version;
  return (
    <span className="text-sm whitespace-nowrap tabular-nums">
      <span className="font-mono">v{d.version}</span>{' '}
      {behind > 0 ? <span className="text-xs text-amber-700 dark:text-amber-400">{behind} behind</span> : <span className="text-xs text-muted-foreground">latest</span>}
    </span>
  );
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex items-center justify-between border-b bg-muted/50 px-3 py-1.5">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <CopyButton text={code} variant="ghost" size="sm" />
      </div>
      <pre className="overflow-x-auto bg-zinc-950 p-3 font-mono text-[11.5px] leading-relaxed text-zinc-200">{code}</pre>
    </div>
  );
}

/** How to connect the channel: the snippet, request or routing a developer or mail admin needs. */
export function DeploymentSetup({ d, onReconnect, reconnecting }: { d: Deployment; onReconnect?: () => void; reconnecting?: boolean }) {
  if (d.channel === 'widget' && d.widget) {
    const snippet = `<script src="https://cdn.northfieldbank.com/ops-ai/widget-1.4.2.js"\n  integrity="sha384-Q8mJ3yN0vR2kXwTf6pLd9aHs4eB7cU1oZgVy5iKnM2tPqW8rSx3jF0lAbCdE9hGu"\n  crossorigin="anonymous"\n  data-deployment="${d.id}"\n  data-position="${d.widget.position}"\n  async></script>`;
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">Paste before the closing body tag on any page of an allowed domain. The widget refuses to load anywhere else.</p>
        <CodeBlock label="Embed snippet" code={snippet} />
        <div className="text-sm">
          <span className="text-muted-foreground">Allowed domains: </span>
          {d.widget.allowedDomains.join(', ')}
        </div>
      </div>
    );
  }
  if (d.channel === 'api' && d.api) {
    const curl = `curl -X POST ${d.api.endpoint} \\\n  -H "Authorization: Bearer ${d.api.keyPrefix}…" \\\n  -H "Content-Type: application/json" \\\n  -d '{ "input": { "accountId": "8821-004417" } }'`;
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Runs that hit an approval gate return <code className="font-mono text-xs">202</code> with a run id; poll it or receive the result on your webhook.
        </p>
        <CodeBlock label="Endpoint" code={d.api.endpoint} />
        <CodeBlock label="Example request" code={curl} />
        <div className="text-sm">
          <span className="text-muted-foreground">Rate limit: </span>
          {d.api.rateLimitPerMinute.toLocaleString()} requests a minute
        </div>
      </div>
    );
  }
  if (d.channel === 'email' && d.email) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">Each new email thread opens a case; replies in the thread land on the same case.</p>
        {d.email.sync && (
          <div
            className={cn(
              'flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm',
              d.email.sync.status === 'error' ? 'border-destructive/30 bg-destructive/5 text-destructive' : 'bg-muted/30',
            )}
            data-testid="mailbox-sync"
          >
            <span className="font-medium">{syncText(d.email.sync).title}</span>
            <span className={d.email.sync.status === 'error' ? '' : 'text-muted-foreground'}>{syncText(d.email.sync).detail}</span>
            {d.email.sync.status === 'error' && onReconnect && (
              <Button size="sm" variant="outline" className="ml-auto" disabled={reconnecting} onClick={onReconnect}>
                Reconnect
              </Button>
            )}
          </div>
        )}
        <CodeBlock label="Shared mailbox" code={d.email.inboundAddress} />
        {d.email.folders && (
          <div className="text-sm">
            <span className="text-muted-foreground">Folders: </span>
            {d.email.folders.join(', ')}
            {d.email.securityScan && <span className="text-muted-foreground"> · scanned before reading</span>}
            {d.email.archive && <span className="text-muted-foreground"> · archived with the case</span>}
          </div>
        )}
        <div className="text-sm">
          <span className="text-muted-foreground">Replies from: </span>
          {d.email.replyFrom}
        </div>
        <div className="text-sm">
          <span className="text-muted-foreground">Replies: </span>
          {d.email.repliesNeedReview ? 'wait for a person in Reviews before sending' : 'send automatically'}
        </div>
      </div>
    );
  }
  return null;
}
