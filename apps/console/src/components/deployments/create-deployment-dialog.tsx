'use client';

import * as React from 'react';
import { CheckCircle2, Pencil } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Stepper } from '@/components/shared/stepper';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { TagInput } from '@/components/shared/tag-input';
import type { DeployChannel, DeploymentInput, DeployEnvironment, Workflow } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

import { CHANNELS } from './deployment-meta';

const STEPS = ['Channel', 'Configure', 'Review'] as const;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DOMAIN_RE = /^(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)+$/i;

interface Values {
  name: string;
  workflowId: string;
  channel: DeployChannel;
  environment: DeployEnvironment;
  title: string;
  welcome: string;
  domains: string;
  position: 'right' | 'left';
  rateLimit: string;
  inbound: string;
  replyFrom: string;
  repliesNeedReview: boolean;
  /** Shared mailbox consent (Microsoft 365, app-only). Required before mail can be read. */
  mailboxConnected: boolean;
  folders: string[];
  securityScan: boolean;
  archive: boolean;
}

const initial = (workflowId = ''): Values => ({
  name: '',
  workflowId,
  channel: 'widget',
  environment: 'staging',
  title: 'Ask Northfield',
  welcome: 'Hi! How can we help today?',
  domains: '',
  position: 'right',
  rateLimit: '600',
  inbound: '',
  replyFrom: '',
  repliesNeedReview: true,
  mailboxConnected: false,
  folders: ['Inbox'],
  securityScan: true,
  archive: true,
});

/**
 * Three-step create per the wizard rules. Only published workflows are offered, because a deployment serves
 * a published version and never a draft. New deployments default to staging; promote from the deployment sheet.
 */
export function CreateDeploymentDialog({
  open,
  onOpenChange,
  workflows,
  fixedWorkflowId,
  initialChannel,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflows: Pick<Workflow, 'id' | 'name' | 'status' | 'version'>[];
  fixedWorkflowId?: string;
  /** Channel preselected on open, e.g. `email` from the palette's Connect mailbox. */
  initialChannel?: DeployChannel;
  onSubmit: (input: DeploymentInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [step, setStep] = React.useState(1);
  const [v, setV] = React.useState<Values>({ ...initial(fixedWorkflowId), channel: initialChannel ?? 'widget' });
  const [touched, setTouched] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (open) {
      setStep(1);
      setV({ ...initial(fixedWorkflowId), channel: initialChannel ?? 'widget' });
      setTouched(false);
      setSubmitError(null);
    }
  }, [open, fixedWorkflowId, initialChannel]);
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  const set = <K extends keyof Values>(k: K, val: Values[K]) => setV((s) => ({ ...s, [k]: val }));
  const published = workflows.filter((w) => w.status !== 'draft');
  const wf = workflows.find((w) => w.id === v.workflowId);
  const domains = v.domains.split(',').map((d) => d.trim()).filter(Boolean);
  const errors = {
    name: v.name.trim() ? undefined : 'Name the deployment, e.g. Website chat.',
    workflowId: v.workflowId ? (wf?.status === 'draft' ? 'Publish this workflow first.' : undefined) : 'Choose a published workflow.',
    domains: v.channel !== 'widget' ? undefined : !domains.length ? 'Add at least one domain the widget may load on.' : domains.find((d) => !DOMAIN_RE.test(d)) ? `${domains.find((d) => !DOMAIN_RE.test(d))} is not a domain.` : undefined,
    rateLimit: v.channel !== 'api' ? undefined : Number(v.rateLimit) > 0 ? undefined : 'Enter requests per minute.',
    inbound: v.channel !== 'email' ? undefined : EMAIL_RE.test(v.inbound) ? undefined : 'Enter the address customers write to.',
    mailbox: v.channel !== 'email' || v.mailboxConnected ? undefined : 'Connect the mailbox so the workflow can read it.',
    folders: v.channel !== 'email' || v.folders.length ? undefined : 'Watch at least one folder.',
    replyFrom: v.channel !== 'email' ? undefined : /[^\s<@]+@[^\s@>]+\.[^\s@>]+/.test(v.replyFrom) ? undefined : 'Include the sender address, e.g. Team name <team-inbox@example.com>.',
  };
  const err = (k: keyof typeof errors) => (touched ? errors[k] : undefined);
  const valid = !Object.values(errors).some(Boolean);

  const toInput = (): DeploymentInput => ({
    name: v.name.trim(),
    workflowId: v.workflowId,
    channel: v.channel,
    environment: v.environment,
    widget: v.channel === 'widget' ? { title: v.title, welcomeMessage: v.welcome, allowedDomains: domains, position: v.position } : undefined,
    api: v.channel === 'api' ? { rateLimitPerMinute: Number(v.rateLimit), keyPrefix: '' } : undefined,
    email: v.channel === 'email' ? { inboundAddress: v.inbound.trim(), replyFrom: v.replyFrom.trim(), repliesNeedReview: v.repliesNeedReview, folders: v.folders, securityScan: v.securityScan, archive: v.archive } : undefined,
  });

  const summary: [string, string][] = [
    ['Workflow', wf ? `${wf.name} · serves v${wf.version}` : '—'],
    ['Channel', CHANNELS[v.channel].label],
    ['Environment', v.environment === 'production' ? 'Production' : 'Staging'],
    ...(v.channel === 'widget' ? ([['Domains', domains.join(', ')], ['Title', v.title]] as [string, string][]) : []),
    ...(v.channel === 'api' ? ([['Rate limit', `${v.rateLimit} / minute`]] as [string, string][]) : []),
    ...(v.channel === 'email'
      ? ([
          ['Mailbox', `${v.inbound} · ${v.folders.join(', ')}`],
          ['Security scan', v.securityScan ? 'Attachments and links scanned before the agent reads them' : 'Off'],
          ['Replies from', v.replyFrom],
          ['Replies', v.repliesNeedReview ? 'Wait for review' : 'Send automatically'],
        ] as [string, string][])
      : []),
  ];

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New deployment"
      description={`Step ${step} of ${STEPS.length} · ${STEPS[step - 1]}`}
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="deploy-stepper" />}
      bodyRef={bodyRef}
      bodyClassName="h-[min(26rem,calc(85vh-11rem))] flex-none"
      footer={
        <div className="flex w-full justify-between gap-2">
          <Button variant="ghost" onClick={() => (step === 1 ? onOpenChange(false) : setStep(step - 1))} disabled={isPending}>
            {step === 1 ? 'Cancel' : 'Back'}
          </Button>
          {step < 3 ? (
            <Button
              onClick={() => {
                if (step === 2 && !valid) return setTouched(true);
                setStep(step + 1);
              }}
            >
              Next
            </Button>
          ) : (
            <LoadingButton
              isLoading={isPending}
              loadingText="Deploying…"
              onClick={async () => {
                try {
                  await onSubmit(toInput());
                  onOpenChange(false);
                } catch (e) {
                  setSubmitError((e as Error).message);
                }
              }}
            >
              Deploy to {v.environment}
            </LoadingButton>
          )}
        </div>
      }
    >
      {step === 1 && (
        <div
          className="grid gap-2"
          role="radiogroup"
          aria-label="Channel"
          onKeyDown={(e) => {
            // Arrow keys move the selection, as in a native radio group; only the selected option is tabbable.
            const keys = Object.keys(CHANNELS) as DeployChannel[];
            const delta = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
            if (!delta) return;
            e.preventDefault();
            const next = keys[(keys.indexOf(v.channel) + delta + keys.length) % keys.length];
            set('channel', next);
            e.currentTarget.querySelector<HTMLButtonElement>(`[data-channel="${next}"]`)?.focus();
          }}
        >
          {(Object.keys(CHANNELS) as DeployChannel[]).map((c) => {
            const meta = CHANNELS[c];
            return (
              <button
                key={c}
                type="button"
                role="radio"
                data-channel={c}
                aria-checked={v.channel === c}
                tabIndex={v.channel === c ? 0 : -1}
                onClick={() => set('channel', c)}
                className={cn('flex items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-muted/40', v.channel === c && 'border-primary bg-primary/5')}
              >
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/50">
                  <meta.icon className="size-4 text-muted-foreground" />
                </div>
                <span>
                  <span className="block text-sm font-medium">{meta.label}</span>
                  <span className="block text-xs text-muted-foreground">{meta.description}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}

      {step === 2 && (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!valid) return setTouched(true);
            setStep(3);
          }}
        >
          <FormField id="dp-name" label="Name" error={err('name')}>
            <Input id="dp-name" autoFocus value={v.name} onChange={(e) => set('name', e.target.value)} placeholder={v.channel === 'email' ? 'e.g. Support inbox' : v.channel === 'api' ? 'e.g. Mobile app' : 'e.g. Website chat'} aria-invalid={!!err('name')} />
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="dp-wf" label="Workflow" error={err('workflowId')} hint={fixedWorkflowId ? undefined : 'Only published workflows can be deployed.'}>
              <Select value={v.workflowId} onValueChange={(x) => set('workflowId', x)} disabled={!!fixedWorkflowId}>
                <SelectTrigger id="dp-wf" className="w-full" aria-invalid={!!err('workflowId')}>
                  <SelectValue placeholder="Choose a workflow" />
                </SelectTrigger>
                <SelectContent>
                  {(fixedWorkflowId ? workflows.filter((w) => w.id === fixedWorkflowId) : published).map((w) => (
                    <SelectItem key={w.id} value={w.id}>
                      {w.name} · v{w.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="dp-env" label="Environment" hint="Start in staging; promote when it behaves.">
              <Select value={v.environment} onValueChange={(x) => set('environment', x as DeployEnvironment)}>
                <SelectTrigger id="dp-env" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="staging">Staging</SelectItem>
                  <SelectItem value="production">Production</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </div>

          {v.channel === 'widget' && (
            <>
              <FormField id="dp-domains" label="Allowed domains" error={err('domains')} hint="Comma separated. *.example.com covers subdomains.">
                <Input id="dp-domains" value={v.domains} onChange={(e) => set('domains', e.target.value)} placeholder="e.g. www.example.com, example.com" aria-invalid={!!err('domains')} />
              </FormField>
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField id="dp-title" label="Widget title">
                  <Input id="dp-title" value={v.title} onChange={(e) => set('title', e.target.value)} />
                </FormField>
                <FormField id="dp-pos" label="Position">
                  <Select value={v.position} onValueChange={(x) => set('position', x as 'right' | 'left')}>
                    <SelectTrigger id="dp-pos" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="right">Bottom right</SelectItem>
                      <SelectItem value="left">Bottom left</SelectItem>
                    </SelectContent>
                  </Select>
                </FormField>
              </div>
              <FormField id="dp-welcome" label="Welcome message" optional>
                <Input id="dp-welcome" value={v.welcome} onChange={(e) => set('welcome', e.target.value)} />
              </FormField>
            </>
          )}

          {v.channel === 'api' && (
            <FormField id="dp-rate" label="Rate limit" error={err('rateLimit')} hint="Requests per minute across all keys. The key is shown once after deploying.">
              <Input id="dp-rate" type="number" min={1} value={v.rateLimit} onChange={(e) => set('rateLimit', e.target.value)} aria-invalid={!!err('rateLimit')} />
            </FormField>
          )}

          {v.channel === 'email' && (
            <>
              <FormField id="dp-in" label="Shared mailbox" error={err('inbound') ?? err('mailbox')} hint="Microsoft 365 shared mailbox. Connecting asks an admin for read and send consent on this mailbox only.">
                <div className="flex flex-wrap gap-2">
                  <Input
                    id="dp-in"
                    type="email"
                    className="min-w-56 flex-1"
                    value={v.inbound}
                    onChange={(e) => setV((s) => ({ ...s, inbound: e.target.value, mailboxConnected: false }))}
                    placeholder="e.g. team-inbox@example.com"
                    aria-invalid={!!(err('inbound') ?? err('mailbox'))}
                  />
                  {v.mailboxConnected ? (
                    <span className="flex items-center gap-1 text-sm text-emerald-700 dark:text-emerald-400" data-testid="mailbox-connected">
                      <CheckCircle2 className="size-4" /> Connected
                    </span>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!EMAIL_RE.test(v.inbound)}
                      onClick={() => setV((s) => ({ ...s, mailboxConnected: true, replyFrom: s.replyFrom || s.inbound }))}
                    >
                      Connect mailbox
                    </Button>
                  )}
                </div>
              </FormField>
              <FormField id="dp-folders" label="Folders to watch" error={err('folders')}>
                <TagInput id="dp-folders" value={v.folders} onChange={(f) => set('folders', f)} suggestions={['Inbox', 'Hardship', 'Escalations']} placeholder="Add a folder…" />
              </FormField>
              <label htmlFor="dp-scan" className="flex items-start justify-between gap-4 rounded-lg border p-3">
                <span>
                  <span className="block text-sm font-medium">Scan attachments and links first</span>
                  <span className="block text-xs text-muted-foreground">Mail that fails the scan opens a case for a person; the agent does not read it.</span>
                </span>
                <Switch id="dp-scan" checked={v.securityScan} onCheckedChange={(c) => set('securityScan', c)} />
              </label>
              <label htmlFor="dp-archive" className="flex items-start justify-between gap-4 rounded-lg border p-3">
                <span>
                  <span className="block text-sm font-medium">Archive mail and attachments with the case</span>
                  <span className="block text-xs text-muted-foreground">Kept for the bank&apos;s retention period, linked from the case record.</span>
                </span>
                <Switch id="dp-archive" checked={v.archive} onCheckedChange={(c) => set('archive', c)} />
              </label>
              <FormField id="dp-from" label="Replies come from" error={err('replyFrom')}>
                <Input id="dp-from" value={v.replyFrom} onChange={(e) => set('replyFrom', e.target.value)} placeholder="e.g. Team name <team-inbox@example.com>" aria-invalid={!!err('replyFrom')} />
              </FormField>
              <label htmlFor="dp-review" className="flex items-start justify-between gap-4 rounded-lg border p-3">
                <span>
                  <span className="block text-sm font-medium">Review replies before they send</span>
                  <span className="block text-xs text-muted-foreground">Each outgoing reply waits in Reviews for a person.</span>
                </span>
                <Switch id="dp-review" checked={v.repliesNeedReview} onCheckedChange={(c) => set('repliesNeedReview', c)} />
              </label>
            </>
          )}
          <button type="submit" hidden />
        </form>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          {submitError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{submitError}</p>}
          <div className="rounded-lg border">
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-sm font-medium">{v.name || 'Deployment'}</span>
              <Button variant="ghost" size="sm" onClick={() => setStep(2)}>
                <Pencil className="size-3.5" /> Edit
              </Button>
            </div>
            <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 px-3 py-2.5 text-sm">
              {summary.map(([k, val]) => (
                <React.Fragment key={k}>
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="truncate">{val}</dd>
                </React.Fragment>
              ))}
            </dl>
          </div>
          <p className="text-xs text-muted-foreground">It serves v{wf?.version} until you move it to a newer published version from its sheet.</p>
        </div>
      )}
    </DialogShell>
  );
}
