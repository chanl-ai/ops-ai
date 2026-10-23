'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpRight, Briefcase, CheckCircle2, Circle, Loader2, LockKeyhole, MoreHorizontal, Play, Route, User, UserCheck, XCircle } from 'lucide-react';

import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import type { CardBody, CardButton, CardFact, CardRecordType, CardStepState, CardTone, OpsCardSpec } from '@/lib/types/ops-card';
import { cn } from '@/lib/utils';

const TONE: Record<CardTone, string> = {
  neutral: '',
  info: 'border-primary/30 bg-primary/10 text-primary',
  success: 'border-success/30 bg-success/10 text-success-text',
  warning: 'border-warning/30 bg-warning/10 text-warning-text',
  danger: 'border-destructive/30 bg-destructive/10 text-destructive',
};

const ICON: Record<CardRecordType, typeof Briefcase> = { case: Briefcase, task: UserCheck, run: Route, start: Play, customer: User };

const STEP_ICON: Record<CardStepState, React.ReactNode> = {
  pending: <Circle className="size-4 text-muted-foreground" />,
  running: <Loader2 className="size-4 animate-spin text-primary" />,
  done: <CheckCircle2 className="size-4 text-success-text" />,
  failed: <XCircle className="size-4 text-destructive" />,
};

/**
 * The one card an agent shows in chat (c-469), drawn the same in the console and the embedded chat: the record's
 * type and title, one status, a body, at most two buttons plus More, and Open to the record's page. It only draws:
 * what a button does, and whether it shows at all, is decided by the record's own rules (components/chat/record-cards).
 * `children` is a body of its own, such as a workflow's start form; `outcome` replaces the buttons once one acted.
 */
export function OpsCard({ spec, buttons = [], outcome, children, className }: { spec: OpsCardSpec; buttons?: CardButton[]; outcome?: string; children?: React.ReactNode; className?: string }) {
  const Icon = ICON[spec.record.type];
  return (
    <Card className={cn('gap-3 shadow-none', className)} data-testid="ops-card" data-record={spec.record.type} data-state={outcome ? 'acted' : 'open'}>
      <CardHeader className="gap-1 px-4 pt-4">
        <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
          <Icon className="size-3.5 shrink-0" />
          <span className="truncate">{spec.record.label}</span>
        </div>
        <CardTitle className="text-base leading-snug">{spec.title}</CardTitle>
        {spec.subtitle && <CardDescription>{spec.subtitle}</CardDescription>}
        {spec.status && (
          <CardAction>
            <Badge variant="outline" className={cn('whitespace-nowrap', TONE[spec.status.tone])} data-testid="ops-card-status">
              {spec.status.text}
            </Badge>
          </CardAction>
        )}
      </CardHeader>
      {(spec.body.kind !== 'none' || children) && (
        <CardContent className="flex flex-col gap-3 px-4 pb-0">
          <Body body={spec.body} />
          {children}
        </CardContent>
      )}
      <CardFooter className="flex-wrap items-center gap-x-3 gap-y-2 border-t px-4 pb-3 [.border-t]:pt-3">
        <Button asChild variant="link" size="sm" className="h-auto px-0 text-muted-foreground">
          <Link href={spec.record.href} data-testid="ops-card-open">
            {spec.record.open}
            <ArrowUpRight className="size-3.5" />
          </Link>
        </Button>
        {outcome ? (
          <p className="basis-full text-sm text-muted-foreground sm:order-first sm:basis-auto sm:flex-1" role="status" data-testid="ops-card-outcome">
            {outcome}
          </p>
        ) : (
          buttons.length > 0 && <Buttons buttons={buttons} />
        )}
      </CardFooter>
    </Card>
  );
}

function Buttons({ buttons }: { buttons: CardButton[] }) {
  const [pending, setPending] = React.useState<string>();
  const press = async (b: CardButton) => {
    setPending(b.id);
    try {
      await b.onPress();
    } finally {
      setPending(undefined);
    }
  };
  // The primary action sits last, where the eye ends on a row of buttons.
  const shown = [...buttons.slice(0, 2)].sort((a, b) => Number(!!a.primary) - Number(!!b.primary));
  const more = buttons.slice(2);
  return (
    <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
      {shown.map((b) => (
        <LoadingButton
          key={b.id}
          size="sm"
          variant={b.primary ? 'default' : b.destructive ? 'destructive' : 'outline'}
          isLoading={pending === b.id}
          disabled={!!pending && pending !== b.id}
          onClick={() => void press(b)}
          title={b.locked ? 'Asks you to sign in again first' : undefined}
          data-testid={`ops-card-action-${b.id}`}
        >
          {b.locked && <LockKeyhole className="size-3.5" />}
          {b.label}
        </LoadingButton>
      ))}
      {more.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon" variant="ghost" className="size-8" aria-label="More actions" disabled={!!pending}>
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {more.map((b) => (
              <DropdownMenuItem key={b.id} variant={b.destructive ? 'destructive' : 'default'} onSelect={() => void press(b)}>
                {b.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

function Body({ body }: { body: CardBody }) {
  if (body.kind === 'none') return null;
  if (body.kind === 'facts') return <Facts facts={body.facts} />;
  return (
    <div className="flex flex-col gap-3">
      <ol className="flex flex-col gap-2 text-sm" data-testid="ops-card-steps">
        {body.steps.map((s, i) => (
          <li key={`${i}-${s.title}`} className="flex items-start gap-2" data-state={s.state}>
            <span className="mt-0.5 shrink-0">{STEP_ICON[s.state]}</span>
            <span className={cn('min-w-0', s.state === 'done' && 'text-muted-foreground', s.state === 'running' && 'font-medium')}>{s.title}</span>
          </li>
        ))}
      </ol>
      {body.facts && <Facts facts={body.facts} />}
    </div>
  );
}

function Facts({ facts }: { facts: CardFact[] }) {
  return (
    <dl className="grid grid-cols-[minmax(5.5rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="ops-card-facts">
      {facts.map((f) => (
        <React.Fragment key={f.label}>
          <dt className="text-muted-foreground">{f.label}</dt>
          <dd className={cn('min-w-0 break-words', f.warn && 'font-medium text-warning-text')}>
            {f.href ? (
              <Link href={f.href} className="underline-offset-4 hover:underline">
                {f.value}
              </Link>
            ) : (
              f.value
            )}
          </dd>
        </React.Fragment>
      ))}
    </dl>
  );
}
