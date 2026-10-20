'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, Route } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { KeyValues, Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { plural, relativeTime } from '@/lib/format';

import { AGENT_CHANNELS_HREF, PROVIDER_LABEL, ROOT, SENDER_LABEL, type Connection, type MailboxSettings } from '../_sample/data';
import { channelsStore } from '../_sample/store';
import { useSecretAdder } from './add-secret';
import { ConnectionStatusDot } from './layout';
import { MailboxFields, checkMailbox, type MailboxErrors, type SecretTarget } from './mailbox-fields';

/** Status, the last message received and the replies sender, with the reason when it needs attention. */
export function MailboxStatus({ mailbox }: { mailbox: Connection }) {
  const m = mailbox.mailbox;
  return (
    <div className="flex flex-col gap-4" data-testid="mailbox-status">
      {mailbox.status === 'attention' && mailbox.problem && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>No new mail is being read</AlertTitle>
          <AlertDescription>{mailbox.problem}</AlertDescription>
        </Alert>
      )}
      <Section title="Status">
        <KeyValues
          rows={[
            ['Status', <ConnectionStatusDot status={mailbox.status} at={mailbox.lastActivityAt} problem={mailbox.problem} />],
            ['Last message', mailbox.lastMessage ? <span>“{mailbox.lastMessage.subject}” from {mailbox.lastMessage.from}, {relativeTime(mailbox.lastMessage.at)}</span> : 'None received yet'],
            ['Reads', m ? `${m.folder} · ${PROVIDER_LABEL[m.provider]}` : undefined],
            ['Replies', m ? `From ${m.fromAddress} · ${SENDER_LABEL[m.sender]}` : undefined],
            ['Team', mailbox.team],
          ]}
        />
      </Section>
    </div>
  );
}

/** The workflows whose Email received trigger reads this mailbox, each linking to its canvas. */
export function MailboxWorkflows({ mailbox }: { mailbox: Connection }) {
  return (
    <Section title="Workflows using it" description="Each starts a run for every new email in the folder." flush>
      {mailbox.workflows.length ? (
        <Rows testId="mailbox-workflows">
          {mailbox.workflows.map((w) => (
            <Row key={w.id} href={`/workflows/${w.id}`} leading={<Route className="size-4 text-muted-foreground" />} title={w.name} description={w.id} trailing={<Badge variant={w.status === 'live' ? 'secondary' : 'outline'}>{w.status === 'live' ? 'Live' : 'Draft'}</Badge>} />
          ))}
        </Rows>
      ) : (
        <p className="p-4 text-sm text-muted-foreground" data-testid="mailbox-workflows-empty">
          No workflow watches it yet. Pick it in a workflow’s Email received trigger, as on the{' '}
          <Link href={`${ROOT}/trigger`} className="text-primary underline-offset-4 hover:underline">
            trigger mock
          </Link>
          .
        </p>
      )}
      <p className="border-t px-4 py-3 text-xs text-muted-foreground">
        Agents reach email through these workflows; an agent’s{' '}
        <Link href={AGENT_CHANNELS_HREF} className="text-primary underline-offset-4 hover:underline">
          Channels tab
        </Link>{' '}
        lists the workflows that call it.
      </p>
    </Section>
  );
}

/** A connected mailbox's settings drawer: status, workflows and the same fields as Connect, saved from the footer. */
export function MailboxSheet({ mailbox, onOpenChange }: { mailbox: Connection | null; onOpenChange: (open: boolean) => void }) {
  const [draft, setDraft] = React.useState<MailboxSettings | null>(mailbox?.mailbox ?? null);
  const [errors, setErrors] = React.useState<MailboxErrors>({});
  React.useEffect(() => {
    setDraft(mailbox?.mailbox ?? null);
    setErrors({});
  }, [mailbox?.id, mailbox?.mailbox]);
  const patch = (p: Partial<MailboxSettings>) => (setDraft((d) => (d ? { ...d, ...p } : d)), setErrors({}));
  const onAdded = React.useCallback((t: SecretTarget, name: string) => setDraft((d) => (d ? { ...d, [t]: name } : d)), []);
  const adder = useSecretAdder(onAdded);
  const save = () => {
    if (!mailbox || !draft) return;
    const e = checkMailbox(draft);
    setErrors(e);
    if (Object.keys(e).length) return;
    channelsStore.updateMailbox(mailbox.id, draft);
    toast.success(`${mailbox.name} saved`, { description: 'Design mock: nothing was stored.' });
  };
  const paused = mailbox?.status === 'paused';
  const [confirmPause, setConfirmPause] = React.useState(false);
  return (
    <>
      <DetailSheet
        open={!!mailbox}
        onOpenChange={onOpenChange}
        testId="mailbox-sheet"
        scrollKey={mailbox?.id}
        title={mailbox?.name ?? ''}
        description={mailbox ? `${mailbox.detail} · ${mailbox.mailbox ? PROVIDER_LABEL[mailbox.mailbox.provider] : ''}` : undefined}
        tags={mailbox && <ConnectionStatusDot status={mailbox.status} at={mailbox.lastActivityAt} problem={mailbox.problem} />}
        footerActions={
          mailbox && (
            <>
              <Button type="submit" form="mailbox-sheet-form" data-testid="mailbox-sheet-save">
                Save
              </Button>
              <Button type="button" variant="outline" onClick={() => (paused ? channelsStore.setPaused(mailbox.id, false) : setConfirmPause(true))}>
                {paused ? 'Resume' : 'Pause'}
              </Button>
              <Button asChild variant="ghost">
                <Link href={`${ROOT}/email/${mailbox.id}`}>Open page</Link>
              </Button>
            </>
          )
        }
      >
        {mailbox && draft && (
          <div className="flex min-w-0 flex-col gap-5">
            <MailboxStatus mailbox={mailbox} />
            <MailboxWorkflows mailbox={mailbox} />
            <form
              id="mailbox-sheet-form"
              onSubmit={(e) => {
                e.preventDefault();
                save();
              }}
            >
              <MailboxFields value={draft} onChange={patch} errors={errors} onAddSecret={adder.start} idPrefix="sheet" />
            </form>
          </div>
        )}
      </DetailSheet>
      {adder.dialog}
      {mailbox && (
        <ConfirmActionDialog
          open={confirmPause}
          onOpenChange={setConfirmPause}
          title={`Pause ${mailbox.name}?`}
          consequence={`New mail in ${mailbox.detail} stops starting runs for ${mailbox.workflows.length === 1 ? mailbox.workflows[0].name : plural(mailbox.workflows.length, 'workflow')} until it is resumed. Mail that arrives meanwhile is read on resume.`}
          runsNow
          confirmLabel="Pause mailbox"
          isPending={false}
          onConfirm={async () => {
            channelsStore.setPaused(mailbox.id, true);
            setConfirmPause(false);
          }}
        />
      )}
    </>
  );
}
