'use client';

import * as React from 'react';
import { ArrowUpRight, Check, Loader2, Pencil } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { AppLogo } from '@/components/shared/app-logo';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useCardAppPage } from '@/hooks/systems-queries';
import { titleWithoutCount } from '@/lib/format';
import type { Cell, KindAction, KindNode, KindStatus, Tone } from '@/lib/types/widgets';
import { cn } from '@/lib/utils';

// Cards drawn for an app's records (chat-presentation.html, assistant-routing screens): the app's mark and a title in
// words in the header, the content, and a footer naming the app with one Open link. The link's host is never in the
// data: a card names a path, and the console puts it on the address the app's account signed in to.

const TONE_BADGE: Record<Tone, string> = {
  neutral: '',
  info: 'border-primary/30 bg-primary/10 text-primary',
  success: 'border-success/30 bg-success/10 text-success-text',
  warning: 'border-warning/30 bg-warning/10 text-warning-text',
  danger: 'border-destructive/30 bg-destructive/10 text-destructive-text',
};
const ENTER = 'animate-in fade-in-0 slide-in-from-bottom-1 duration-300 motion-reduce:animate-none';
const text = (v: Cell | undefined) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : typeof v === 'number' ? v.toLocaleString() : v);

/** An app id's last word, for when the team's record of the app cannot be read: `plugin:opsai.salesforce` → Salesforce. */
const nameOf = (app: string) => {
  const word = app.split(/[:.]/).pop() ?? app;
  return word.charAt(0).toUpperCase() + word.slice(1);
};

/** The https origin an account signed in to (its org address), read from the value the sign-in found. */
function originOf(page: { accounts?: { default?: boolean; signInValues?: { kind: string; value?: string }[] }[] } | undefined): string | undefined {
  const accounts = page?.accounts ?? [];
  for (const a of [...accounts.filter((x) => x.default), ...accounts.filter((x) => !x.default)]) {
    for (const v of a.signInValues ?? []) {
      if (v.kind !== 'found' || !v.value) continue;
      try {
        const u = new URL(v.value);
        if (u.protocol === 'https:') return u.origin;
      } catch {
        // Not an address; another found value may be.
      }
    }
  }
  return undefined;
}

/** The app's name and mark from the team's Apps, and where its records open; the id's last word while it loads. */
export function useCardApp(app?: string): { name: string; logo?: string | null; origin?: string } | undefined {
  const page = useCardAppPage(app);
  if (!app) return undefined;
  const card = page.data?.card as { name?: string; logo?: string | null } | undefined;
  return { name: card?.name ?? nameOf(app), logo: card?.logo, origin: originOf(page.data as Parameters<typeof originOf>[0]) };
}


function OpenLink({ origin, open, testId }: { origin?: string; open?: { path: string; label?: string }; testId: string }) {
  // Without the account's address there is nowhere safe to open, so the link is left out rather than guessed.
  if (!open || !origin) return null;
  return (
    <a href={`${origin}${open.path}`} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline" data-testid={testId}>
      {open.label ?? 'Open'} <ArrowUpRight className="size-3" />
    </a>
  );
}

/** Header, body and footer of an app's card. */
function AppCard({
  kind,
  app,
  title,
  subtitle,
  aside,
  footer,
  children,
}: {
  kind: string;
  app?: { name: string; logo?: string | null };
  title: string;
  subtitle?: string;
  aside?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className={cn('overflow-hidden rounded-lg border bg-card text-card-foreground', ENTER)} data-kind={kind}>
      <header className="flex items-start gap-2 border-b px-3 py-2">
        {app ? <AppLogo name={app.name} logo={app.logo} className="mt-0.5" /> : <AppLogo name={title} className="mt-0.5" />}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium break-words">{title}</p>
          {subtitle && <p className="text-xs break-words text-muted-foreground">{subtitle}</p>}
        </div>
        {aside}
      </header>
      {children}
      {footer && <footer className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground">{footer}</footer>}
    </section>
  );
}

function StatusBadge({ status }: { status?: KindStatus }) {
  if (!status) return null;
  return (
    <Badge variant="outline" className={cn('shrink-0', TONE_BADGE[status.tone ?? 'neutral'])} data-testid="card-status">
      {status.tone === 'success' && <Check />}
      {status.text}
    </Badge>
  );
}

/** What to know before a meeting or a call: who and when, then each section's count and top items, one Open link. */
export function BriefKind({ node }: { node: Extract<KindNode, { type: 'brief' }> }) {
  const app = useCardApp(node.app);
  const subtitle = [node.when, node.who].filter(Boolean).join(' · ');
  return (
    <AppCard
      kind="brief"
      app={app}
      title={node.title}
      subtitle={subtitle || undefined}
      aside={<OpenLink origin={app?.origin} open={node.open} testId="brief-open" />}
      footer={app ? <span>{app.name} · Prep brief</span> : undefined}
    >
      <div className="divide-y">
        {node.sections.map((s, i) => (
          <section key={i} className="px-3 py-2" data-testid="brief-section">
            <h4 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <span>{titleWithoutCount(s.title)}</span>
              <Badge variant="secondary" className="h-5 px-1.5 tabular-nums">
                {s.count ?? s.items.length}
              </Badge>
            </h4>
            {s.items.length > 0 ? (
              <ul className="mt-1 flex flex-col gap-1 text-sm">
                {s.items.map((it, j) => (
                  <li key={j} className="flex flex-col gap-x-3 sm:flex-row sm:items-baseline sm:justify-between">
                    {/* The name keeps at least half the row: a long detail beside it squeezed it to one letter a line. */}
                    <span className="min-w-0 break-words sm:min-w-[50%] sm:flex-1">{it.text}</span>
                    {it.detail && <span className="min-w-0 break-words text-xs text-muted-foreground sm:text-right">{it.detail}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">None.</p>
            )}
            {s.note && <p className="mt-1 text-xs text-muted-foreground">{s.note}</p>}
          </section>
        ))}
      </div>
    </AppCard>
  );
}

function ActionButtons({ actions, onReply }: { actions?: KindAction[]; onReply?: (t: string) => void }) {
  if (!actions?.length) return null;
  return (
    <span className="ml-auto flex flex-wrap justify-end gap-2">
      {actions.map((a, i) => (
        <Button key={a.label} size="sm" variant={i === actions.length - 1 ? 'default' : 'outline'} disabled={!onReply} onClick={() => onReply?.(a.reply)}>
          {a.label}
        </Button>
      ))}
    </span>
  );
}

/**
 * One record and its fields; after a write, each changed field as old → new and a new value alone. The app's cards
 * name the app and open the record in it.
 */
export function EntityKind({ node, onReply }: { node: Extract<KindNode, { type: 'entity' }>; onReply?: (t: string) => void }) {
  const app = useCardApp(node.app);
  const changes = node.fields.some((f) => f.was !== undefined);
  const subtitle = [node.category, node.subtitle].filter(Boolean).join(' · ');
  return (
    <AppCard
      kind="entity"
      app={app}
      title={node.title}
      subtitle={subtitle || undefined}
      aside={<StatusBadge status={node.status} />}
      footer={
        app || node.actions?.length ? (
          <>
            {app && <span>{app.name}</span>}
            <span className="ml-auto flex items-center gap-3">
              <OpenLink origin={app?.origin} open={node.open} testId="entity-open" />
            </span>
          </>
        ) : undefined
      }
    >
      {node.fields.length > 0 &&
        (changes ? (
          <ul className="flex flex-col gap-1.5 px-3 py-3" data-testid="entity-changes">
            {node.fields.map((f, i) => (
              <li key={i} className="grid grid-cols-[minmax(0,7rem)_1fr] gap-x-3 text-sm">
                <span className="text-xs leading-5 text-muted-foreground">{f.label}</span>
                <span className="min-w-0 break-words">
                  {f.was !== undefined && f.was !== null && (
                    <>
                      <span className="text-muted-foreground line-through" data-testid="field-was">
                        {text(f.was)}
                      </span>
                      <span className="px-1.5 text-muted-foreground" aria-label="changed to">
                        →
                      </span>
                    </>
                  )}
                  {text(f.value)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-4 gap-y-2 px-3 py-3 text-sm">
            {node.fields.map((f, i) => (
              <React.Fragment key={i}>
                <dt className="text-muted-foreground">{f.label}</dt>
                <dd className="min-w-0 font-medium break-words tabular-nums">{text(f.value)}</dd>
              </React.Fragment>
            ))}
          </dl>
        ))}
      {!!node.actions?.length && (
        <div className="flex border-t px-3 py-2">
          <ActionButtons actions={node.actions} onReply={onReply} />
        </div>
      )}
    </AppCard>
  );
}

type FormNode = Extract<KindNode, { type: 'form' }>;

/** A form's answers as the message the agent reads: its reply, then each filled field by label. */
export function answerText(node: FormNode, values: Record<string, Cell>): string {
  const filled = node.fields.filter((f) => values[f.name] !== '' && values[f.name] !== null && values[f.name] !== undefined).map((f) => `${f.label}: ${text(values[f.name])}`);
  return filled.length ? `${node.submit.reply} (${filled.join(', ')})` : node.submit.reply;
}

/**
 * Fields the person fills or checks; Submit sends the values as their next message, so writing stays the agent's
 * tool call. A field the app refused comes back marked, with the app's reason under it.
 */
export function FormKind({
  node,
  onReply,
  onSubmit,
}: {
  node: FormNode;
  onReply?: (text: string) => void;
  /** A shaped form (a tool's form) submits its values to that tool instead of sending a message. */
  onSubmit?: (values: Record<string, Cell>) => Promise<unknown>;
}) {
  const app = useCardApp(node.app);
  const [values, setValues] = React.useState<Record<string, Cell>>(() => Object.fromEntries(node.fields.map((f) => [f.name, f.value ?? (f.type === 'boolean' ? false : '')])));
  const [state, setState] = React.useState<'open' | 'sending' | 'sent'>('open');
  const send = onSubmit ?? (onReply && ((v: Record<string, Cell>) => (onReply(answerText(node, v)), Promise.resolve())));
  const missing = node.fields.some((f) => f.required && (values[f.name] === '' || values[f.name] === null));
  const set = (k: string, v: Cell) => setValues((x) => ({ ...x, [k]: v }));
  const disabled = !send || state !== 'open';
  return (
    <AppCard kind="form" app={app} title={node.title ?? 'Fill in'} subtitle={node.subtitle}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!send) return;
          setState('sending');
          send(values).then(
            () => setState('sent'),
            () => setState('open'),
          );
        }}
      >
        <div className="grid gap-3 px-3 py-3 sm:grid-cols-2">
          {node.fields.map((f) => {
            const id = `wk-${f.name}`;
            if (f.type === 'boolean')
              return (
                <label key={f.name} className="flex items-center gap-2 text-sm sm:col-span-2">
                  <Switch id={id} checked={values[f.name] === true} disabled={disabled} onCheckedChange={(v) => set(f.name, v)} /> {f.label}
                </label>
              );
            const invalid = f.error ? true : undefined;
            return (
              <FormField key={f.name} id={id} label={f.label} optional={!f.required} error={f.error} className={cn(f.type === 'textarea' && 'sm:col-span-2')}>
                {f.type === 'select' ? (
                  <Select value={String(values[f.name] ?? '')} disabled={disabled} onValueChange={(v) => set(f.name, v)}>
                    <SelectTrigger id={id} className="w-full" aria-invalid={invalid}>
                      <SelectValue placeholder={f.placeholder ?? 'Choose'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(f.options ?? []).map((o) => (
                        <SelectItem key={o} value={o}>
                          {o}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : f.type === 'textarea' ? (
                  <Textarea id={id} rows={3} placeholder={f.placeholder} value={String(values[f.name] ?? '')} disabled={disabled} aria-invalid={invalid} onChange={(e) => set(f.name, e.target.value)} />
                ) : (
                  <Input
                    id={id}
                    type={f.type === 'date' ? 'date' : 'text'}
                    inputMode={f.type === 'number' ? 'decimal' : undefined}
                    placeholder={f.placeholder}
                    value={String(values[f.name] ?? '')}
                    disabled={disabled}
                    aria-invalid={invalid}
                    onChange={(e) => set(f.name, f.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)}
                  />
                )}
              </FormField>
            );
          })}
        </div>
        <footer className="flex flex-wrap items-center gap-2 border-t px-3 py-2">
          {node.note && <span className="min-w-0 text-xs text-muted-foreground">{node.note}</span>}
          <span className="ml-auto flex gap-2">
            {node.edit && (
              <Button type="button" size="sm" variant="outline" disabled={!onReply || state !== 'open'} onClick={() => onReply?.(node.edit!.reply)} data-testid="form-edit">
                <Pencil />
                {node.edit.label}
              </Button>
            )}
            <Button type="submit" size="sm" disabled={!send || missing || state !== 'open'} data-testid="form-submit">
              {state === 'sending' ? <Loader2 className="animate-spin" /> : state === 'open' ? <Check /> : null}
              {state === 'sent' ? (node.submit.done ?? 'Sent') : node.submit.label}
            </Button>
          </span>
        </footer>
      </form>
    </AppCard>
  );
}
