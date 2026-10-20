'use client';

import * as React from 'react';
import Link from 'next/link';
import { Bot, CircleStop, Mail, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { DetailSheet } from '@/components/shared/detail-sheet';
import { FormField } from '@/components/shared/form-field';
import { Combobox } from '@/components/shared/setting/pickers';
import { KeyValues, Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import { ConnectMailbox } from '../_parts/connect-mailbox';
import { ChannelsPageLayout, ConnectionStatusDot } from '../_parts/layout';
import { FOLDERS, PROVIDER_LABEL, ROOT, TRIGGER_WORKFLOW } from '../_sample/data';
import { channelsStore, useConnections } from '../_sample/store';

/** The run input an Email received trigger gives every run, as the canvas's trigger sheet lists it. */
const EMAIL_INPUT: [string, string][] = [
  ['from', 'The sender’s address'],
  ['subject', 'The subject line'],
  ['body', 'The message text'],
  ['attachments', 'Each attachment as a Files id, name, type and size'],
];

/**
 * A mock of the workflow canvas's trigger sheet for Email received: the mailbox comes from a picker of connected
 * mailboxes, and "Connect a mailbox" opens the channels page's connect form in place, as a dialog.
 */
export default function TriggerPreview() {
  const mailboxes = useConnections().filter((c) => c.type === 'email');
  const bound = mailboxes.find((m) => m.workflows.some((w) => w.id === TRIGGER_WORKFLOW.id));
  const [sheetOpen, setSheetOpen] = React.useState(true);
  const [connectOpen, setConnectOpen] = React.useState(false);
  const [mailboxId, setMailboxId] = React.useState<string | null>(bound?.id ?? null);
  const [folder, setFolder] = React.useState('Inbox');
  const [from, setFrom] = React.useState('');
  const [subject, setSubject] = React.useState('');
  const [attachment, setAttachment] = React.useState(true);
  const [error, setError] = React.useState<string | undefined>();
  const picked = mailboxes.find((m) => m.id === mailboxId);

  const pick = (id: string) => {
    setMailboxId(id);
    setFolder(mailboxes.find((m) => m.id === id)?.mailbox?.folder ?? 'Inbox');
    setError(undefined);
  };
  const save = () => {
    if (!mailboxId) return setError('Pick the mailbox this workflow watches.');
    channelsStore.bindTrigger(mailboxId);
    toast.success('Saved version 2', { description: `${TRIGGER_WORKFLOW.name} watches ${picked?.detail}. Design mock: nothing was stored.` });
  };

  return (
    <ChannelsPageLayout title="Email received trigger" description="How a workflow's trigger picks a connected mailbox, or connects one without leaving the canvas">
      <Section
        title={TRIGGER_WORKFLOW.name}
        description="The workflow canvas, drawn as its steps. Open the trigger to set it up."
        actions={<Badge variant="outline">Draft</Badge>}
        flush
      >
        <Rows testId="trigger-steps">
          <Row onClick={() => setSheetOpen(true)} leading={<Mail className="size-4 text-muted-foreground" />} title="Levy notice arrives" description={picked ? `Email received · ${picked.detail} › ${folder}` : 'Email received · no mailbox picked'} trailing={<Badge variant="secondary">Trigger</Badge>} />
          <Row leading={<Bot className="size-4 text-muted-foreground" />} title="Read the notice" description="Agent step · Business documents agent" />
          <Row leading={<CircleStop className="size-4 text-muted-foreground" />} title="Done" description="End" />
        </Rows>
      </Section>

      <DetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        modal={false}
        testId="trigger-sheet"
        title="Levy notice arrives"
        description="Email received · Starts a run for each new email in a mailbox"
        tags={<Badge variant="outline">Trigger</Badge>}
        footerActions={
          <Button type="submit" form="trigger-form" data-testid="trigger-save">
            Save version
          </Button>
        }
      >
        <form
          id="trigger-form"
          className="flex min-w-0 flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <FormField id="trigger-mailbox" label="Mailbox" error={error} hint="The workspace’s connected mailboxes. A new one connects here without leaving the canvas.">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
              <div className="min-w-0 flex-1" data-testid="trigger-mailbox-picker">
                <Combobox id="trigger-mailbox" options={mailboxes.map((m) => ({ value: m.id, label: m.name, hint: `${m.detail} · ${m.mailbox ? PROVIDER_LABEL[m.mailbox.provider] : ''}` }))} value={mailboxId} onChange={pick} noun="mailboxes" placeholder="Choose a mailbox" />
              </div>
              <Button type="button" variant="outline" onClick={() => setConnectOpen(true)} data-testid="trigger-connect-mailbox">
                <Plus className="size-4" /> Connect a mailbox
              </Button>
            </div>
          </FormField>
          {picked && (
            <Rows testId="trigger-picked">
              <Row
                leading={<Mail className="size-4 text-muted-foreground" />}
                title={picked.name}
                description={picked.detail}
                trailing={
                  <>
                    <ConnectionStatusDot status={picked.status} at={picked.lastActivityAt} problem={picked.problem} />
                    <Button asChild variant="ghost" size="sm">
                      <Link href={`${ROOT}/email/${picked.id}`}>Open</Link>
                    </Button>
                  </>
                }
                wrap
              />
            </Rows>
          )}
          {picked && picked.status !== 'connected' && (
            <Alert>
              <AlertTitle>{picked.status === 'paused' ? 'This mailbox is paused' : 'This mailbox needs attention'}</AlertTitle>
              <AlertDescription>{picked.problem ?? 'Its mail starts no runs until it is resumed on Channels.'}</AlertDescription>
            </Alert>
          )}
          <FormField id="trigger-folder" label="Folder">
            <div className="w-full sm:w-1/2">
              <Combobox id="trigger-folder" options={FOLDERS.map((f) => ({ value: f, label: f }))} value={folder} onChange={setFolder} noun="folders" />
            </div>
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="trigger-from" label="From contains" optional>
              <Input id="trigger-from" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="e.g. @court.example" className="bg-card" />
            </FormField>
            <FormField id="trigger-subject" label="Subject contains" optional>
              <Input id="trigger-subject" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. garnishment" className="bg-card" />
            </FormField>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="trigger-attachment" checked={attachment} onCheckedChange={(v) => setAttachment(v === true)} />
            <Label htmlFor="trigger-attachment">Only emails with an attachment</Label>
          </div>
          <Section title="How it starts" description="Every run of this workflow begins here.">
            <KeyValues
              rows={[
                ['From a mailbox', picked ? `A new email in ${picked.detail}, folder ${folder}, that matches the filters above. Mail already there when the workflow goes live starts nothing.` : 'Pick a mailbox above.'],
                ['When it goes live', 'Publishing puts the workflow on the mailbox; the mailbox’s page then lists it'],
                ['From here', 'Test run, with an email you type as JSON'],
              ]}
            />
          </Section>
          <Section title="Run input" description="What every run receives from the email.">
            <KeyValues rows={EMAIL_INPUT.map(([name, what]) => [name, <span className="text-muted-foreground">{what}</span>])} />
          </Section>
        </form>
      </DetailSheet>

      <ConnectMailbox
        shell="dialog"
        open={connectOpen}
        onOpenChange={setConnectOpen}
        onConnected={(id) => {
          setMailboxId(id);
          setError(undefined);
        }}
      />
    </ChannelsPageLayout>
  );
}
