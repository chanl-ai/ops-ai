'use client';

import * as React from 'react';
import { Route } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { LoadingButton } from '@/components/shared/loading-button';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { KeyValues, Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useChangeChannel } from '@/hooks/channel-queries';
import { useEditMailbox } from '@/hooks/channels-queries';
import { plural, relativeTime } from '@/lib/format';
import type { Mailbox } from '@/lib/types/channels';

import { MailboxFields, PROVIDER_LABEL, checkMailbox, formOf, toInput, type MailboxErrors, type MailboxForm } from './mailbox-fields';

/** A mailbox's state as a dot and a word: paused, read, or not read yet. */
export function MailboxStatusDot({ mailbox }: { mailbox: Mailbox }) {
  if (mailbox.paused) return <StatusDot status="idle" label="Paused" />;
  if (mailbox.lastReadAt) return <StatusDot status="ok" label="Reading" at={mailbox.lastReadAt} />;
  return <StatusDot status="idle" label={mailbox.workflows.length ? 'Not read yet' : 'No workflow yet'} />;
}

export function MailboxStatus({ mailbox }: { mailbox: Mailbox }) {
  return (
    <Section title="Status">
      <KeyValues
        rows={[
          ['Status', <MailboxStatusDot mailbox={mailbox} />],
          ['Last read', mailbox.lastReadAt ? relativeTime(mailbox.lastReadAt) : 'Not yet'],
          ['Reads', `${mailbox.folder} · ${PROVIDER_LABEL[mailbox.provider]}`],
          ['Password', mailbox.passwordSecret ? <code className="font-mono text-xs">{mailbox.passwordSecret}</code> : 'None'],
          ['Replies', mailbox.sender === 'none' ? 'Not sent from this mailbox' : `From ${mailbox.fromAddress} · ${mailbox.sender === 'smtp' ? 'SMTP' : 'Resend'}`],
          ['Team', mailbox.teamId],
        ]}
      />
    </Section>
  );
}

/** The live workflows whose Email received trigger reads this mailbox. */
export function MailboxWorkflows({ mailbox }: { mailbox: Mailbox }) {
  return (
    <Section title="Workflows using it" description="Each starts a run for every new email in the folder." flush>
      {mailbox.workflows.length ? (
        <Rows testId="mailbox-workflows">
          {mailbox.workflows.map((w) => (
            <Row key={w.id} href={`/workflows/definitions/${encodeURIComponent(w.id)}`} leading={<Route className="size-4 text-muted-foreground" />} title={w.name} description={w.id} trailing={<Badge variant="secondary">Live v{w.version}</Badge>} />
          ))}
        </Rows>
      ) : (
        <p className="p-4 text-sm text-muted-foreground" data-testid="mailbox-workflows-empty">
          No live workflow watches it yet. Pick it in a workflow’s Email received trigger and publish the workflow.
        </p>
      )}
    </Section>
  );
}

/** The saved mailbox's settings, saved from the button; pause and resume beside it, with the consequence stated. */
export function MailboxSettingsForm({ mailbox }: { mailbox: Mailbox }) {
  const edit = useEditMailbox(mailbox.id);
  const change = useChangeChannel();
  const [form, setForm] = React.useState<MailboxForm>(() => formOf(mailbox));
  const [errors, setErrors] = React.useState<MailboxErrors>({});
  const [failure, setFailure] = React.useState<string | null>(null);
  const [confirmPause, setConfirmPause] = React.useState(false);
  React.useEffect(() => {
    setForm(formOf(mailbox));
  }, [mailbox]);
  const patch = (p: Partial<MailboxForm>) => (setForm((f) => ({ ...f, ...p })), setErrors({}), setFailure(null));
  const save = async () => {
    const e = checkMailbox(form);
    setErrors(e);
    if (Object.keys(e).length) return;
    const { provider: _p, ...input } = toInput(form);
    try {
      await edit.mutateAsync(input);
      toast.success(`${form.name} saved`);
    } catch (err) {
      setFailure(err instanceof Error ? err.message : 'The mailbox could not be saved.');
    }
  };
  const setPaused = async (paused: boolean) => {
    try {
      await change.mutateAsync({ id: mailbox.id, patch: { paused } });
      toast.success(paused ? `${mailbox.name} paused` : `${mailbox.name} resumed`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'The mailbox could not be changed.');
    }
  };
  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Section title="Settings" description="How the mailbox signs in and the folder it watches.">
          <div className="flex flex-col gap-4">
            {failure && (
              <Alert variant="destructive" data-testid="mailbox-save-error">
                <AlertDescription>{failure}</AlertDescription>
              </Alert>
            )}
            <MailboxFields value={form} onChange={patch} errors={errors} idPrefix="mailbox" testTarget={() => ({ id: mailbox.id })} />
            <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
              <Button type="button" variant="outline" onClick={() => (mailbox.paused ? void setPaused(false) : setConfirmPause(true))} data-testid="mailbox-pause">
                {mailbox.paused ? 'Resume' : 'Pause'}
              </Button>
              <LoadingButton type="submit" isLoading={edit.isPending} loadingText="Saving…" data-testid="mailbox-save">
                Save
              </LoadingButton>
            </div>
          </div>
        </Section>
      </form>
      <ConfirmActionDialog
        open={confirmPause}
        onOpenChange={setConfirmPause}
        title={`Pause ${mailbox.name}?`}
        consequence={`New mail in ${mailbox.address} stops starting runs for ${mailbox.workflows.length === 1 ? mailbox.workflows[0].name : plural(mailbox.workflows.length, 'workflow')} until it is resumed. Mail that arrives meanwhile is read on resume.`}
        runsNow
        confirmLabel="Pause mailbox"
        isPending={change.isPending}
        onConfirm={async () => {
          await setPaused(true);
          setConfirmPause(false);
        }}
      />
    </>
  );
}
