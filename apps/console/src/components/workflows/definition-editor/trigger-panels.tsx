'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, ChevronDown, Plus } from 'lucide-react';

import { ConnectMailbox } from '@/components/channels/connect-mailbox';
import { MailboxStatusDot } from '@/components/channels/mailbox-panels';
import { KeyValues, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { useMailboxes } from '@/hooks/channels-queries';
import type { EngineNode } from '@/lib/types/engine';

import { ShareAsForm } from './share-as-form';

/**
 * The "How it starts" slot of the step sheet: one panel per trigger type, shown under Problems and above What it
 * receives, for trigger steps only. A trigger type adds its panel as one entry of TRIGGER_PANELS; the sheet never
 * names a trigger type itself. A panel edits the step through `onChange` (saved with the workflow, as every setting
 * is); a panel that saves on its own (a schedule, a folder watch) keeps its own Save button and says so in its text.
 */
export interface TriggerPanelProps {
  node: EngineNode;
  workflowId: string;
  readOnly: boolean;
  /** Replaces the step's parameters; the workflow's autosave stores them. */
  onChange: (parameters: Record<string, unknown>) => void;
}

const EMAIL_TRIGGER = 'ops.trigger.email';
const REQUEST_TRIGGER = 'ops.trigger.request';

type InputSchema = { properties?: Record<string, { type?: string; description?: string }>; required?: string[] };

function EmailPanel({ node, readOnly, onChange }: TriggerPanelProps) {
  const parameters = node.parameters ?? {};
  return <EmailTriggerDetails parameters={parameters} readOnly={readOnly} onConnected={(address) => onChange({ ...parameters, mailbox: address })} />;
}

function RequestPanel({ node, workflowId, readOnly }: TriggerPanelProps) {
  const schema = (node.parameters?.inputSchema ?? {}) as InputSchema;
  return (
    <>
      <TriggerDetails workflowId={workflowId} schema={schema} />
      <ShareAsForm workflowId={workflowId} schema={schema as Record<string, unknown>} readOnly={readOnly} />
    </>
  );
}

function DefaultPanel({ node, workflowId }: TriggerPanelProps) {
  return <TriggerDetails workflowId={workflowId} schema={(node.parameters?.inputSchema ?? {}) as InputSchema} />;
}

/** Trigger type id to its panel; a trigger type with no entry shows how a run starts from an app, an agent or here. */
export const TRIGGER_PANELS: Record<string, React.ComponentType<TriggerPanelProps>> = {
  [EMAIL_TRIGGER]: EmailPanel,
  [REQUEST_TRIGGER]: RequestPanel,
};

/** The slot itself: the trigger type's own panel, or the default one. */
export function HowItStarts(props: TriggerPanelProps) {
  const Panel = TRIGGER_PANELS[props.node.type] ?? DefaultPanel;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="step-how-it-starts">
      <Panel {...props} />
    </div>
  );
}

/** The run input an Email received trigger gives every run: the email, with each attachment already in Files. */
const EMAIL_INPUT: [string, string][] = [
  ['from', "The sender's address"],
  ['subject', 'The subject line'],
  ['body', 'The message text'],
  ['receivedAt', 'When the mailbox received it'],
  ['messageId', 'The Message-ID; a second delivery of the same message starts no run'],
  ['attachments', 'Each attachment as a Files id, name, type and size'],
];

/** How an Email received trigger starts runs, and the input each run gets. */
function EmailTriggerDetails({ parameters, readOnly, onConnected }: { parameters: Record<string, unknown>; readOnly: boolean; /** A mailbox connected from here becomes the trigger's mailbox. */ onConnected: (address: string) => void }) {
  const [connecting, setConnecting] = React.useState(false);
  const mailbox = typeof parameters.mailbox === 'string' && parameters.mailbox ? parameters.mailbox : 'the mailbox you choose below';
  const folder = typeof parameters.folder === 'string' && parameters.folder ? parameters.folder : 'inbox';
  // The picked mailbox as Channels shows it: its state and a way to open it, and a warning when it reads no mail.
  const mailboxes = useMailboxes();
  const picked = typeof parameters.mailbox === 'string' ? mailboxes.data?.find((m) => m.address === parameters.mailbox) : undefined;
  return (
    <>
      {picked && (
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-sm" data-testid="trigger-picked-mailbox">
          <span className="min-w-0 truncate font-medium">{picked.name || picked.address}</span>
          <MailboxStatusDot mailbox={picked} />
          <span className="text-muted-foreground">Reads {picked.folder}</span>
          <Link href={`/build/channels/email/${picked.id}`} className="ml-auto underline underline-offset-2">
            Open
          </Link>
        </div>
      )}
      {picked?.paused && (
        <Alert data-testid="trigger-mailbox-paused">
          <AlertTriangle />
          <AlertTitle>This mailbox is paused</AlertTitle>
          <AlertDescription>No mail is read and no run starts until it is resumed on its Channels page.</AlertDescription>
        </Alert>
      )}
      <div data-testid="trigger-how-it-starts">
        <Section title="How it starts" description="Every run of this workflow begins here.">
          <KeyValues
            rows={[
              [
                'From a mailbox',
                <span>
                  A new email in <span className="font-medium">{mailbox}</span>, folder <span className="font-medium">{folder}</span>, that
                  matches the filters below. Mail already there when the workflow goes live starts nothing.
                </span>,
              ],
              ['When it goes live', 'Publishing puts the workflow on the mailbox; it needs the right to add deployments in this team'],
              ['From here', 'Test run, with an email you type in'],
            ]}
          />
        </Section>
      </div>
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>The mailbox isn’t listed?</span>
          <Button type="button" variant="outline" size="sm" onClick={() => setConnecting(true)} data-testid="trigger-connect-mailbox">
            <Plus className="size-4" /> Connect
          </Button>
          <ConnectMailbox shell="dialog" open={connecting} onOpenChange={setConnecting} onConnected={(m) => onConnected(m.address)} />
        </div>
      )}
      <div data-testid="trigger-run-input">
        <Section title="Run input" description="What every run receives from the email.">
          <KeyValues rows={EMAIL_INPUT.map(([name, what]) => [name, <span className="text-muted-foreground">{what}</span>])} />
        </Section>
      </div>
    </>
  );
}

/** How a run of this workflow starts, and the input it must send. The call and tool name an app or agent uses sit behind
 * Technical details, so the sheet reads in plain words. */
function TriggerDetails({ workflowId, schema }: { workflowId: string; schema: InputSchema }) {
  const fields = Object.entries(schema.properties ?? {});
  return (
    <>
      <div data-testid="trigger-how-it-starts">
        <Section title="How it starts" description="Every run of this workflow begins here.">
          <KeyValues
            rows={[
              ['From an app', 'Another app starts it with a signed-in call'],
              ['From an agent', 'An agent that has this workflow as a tool starts it'],
              ['From here', 'Test run, with an input you type'],
            ]}
          />
          <Collapsible className="mt-3" data-testid="trigger-technical">
            <CollapsibleTrigger className="group flex items-center gap-1 text-xs font-medium text-muted-foreground" data-testid="trigger-technical-toggle">
              <ChevronDown className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
              Technical details
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3">
              <KeyValues
                rows={[
                  ['App call', <code className="font-mono text-xs">POST /v1/runs</code>],
                  ['Agent tool name', <code className="font-mono text-xs break-all">workflow__{workflowId}</code>],
                ]}
              />
            </CollapsibleContent>
          </Collapsible>
        </Section>
      </div>
      <div data-testid="trigger-run-input">
        <Section title="Run input" description="What a run must send; checked against the input form before the first step.">
          {fields.length === 0 ? (
            <p className="text-sm text-muted-foreground">Any input: the input form names no fields.</p>
          ) : (
            <KeyValues
              rows={fields.map(([name, p]) => [
                name,
                <span className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{TYPE_WORDS[p.type ?? ''] ?? 'Any value'}</Badge>
                  {schema.required?.includes(name) && <Badge variant="secondary">required</Badge>}
                  {p.description && <span className="text-muted-foreground">{p.description}</span>}
                </span>,
              ])}
            />
          )}
        </Section>
      </div>
    </>
  );
}

/** A field's JSON type in a builder's words. */
const TYPE_WORDS: Record<string, string> = { string: 'Text', number: 'Number', integer: 'Whole number', boolean: 'Yes or no', object: 'Group of fields', array: 'List' };
