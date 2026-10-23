'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, ChevronDown, Plus, Trash2 } from 'lucide-react';

import { ConnectMailbox } from '@/components/channels/connect-mailbox';
import { MailboxStatusDot } from '@/components/channels/mailbox-panels';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { FormField } from '@/components/shared/form-field';
import { KeyValues, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useMailboxes } from '@/hooks/channels-queries';
import type { DefinitionCheck, EngineNode, EngineNodeType } from '@/lib/types/engine';

import { groupLook } from './definition-node';
import { NodeSettingsForm, type StepRefs } from './node-form';

const KIND: Record<string, string> = { trigger: 'Trigger', data: 'Data', flow: 'Flow', action: 'Action', ai: 'AI', human: 'Person' };
const pretty = (p: Record<string, unknown> | undefined) => JSON.stringify(p ?? {}, null, 2);

type InputSchema = { properties?: Record<string, { type?: string; description?: string }>; required?: string[] };

export interface StepSheetProps {
  node: EngineNode | null;
  type: EngineNodeType | undefined;
  workflowId: string;
  steps: StepRefs;
  /** The server's checks about this step. */
  checks: DefinitionCheck[];
  /** Steps in the order they run; previous and next walk it. */
  order: string[];
  readOnly: boolean;
  onClose: () => void;
  onMove: (id: string) => void;
  onChange: (patch: Partial<Pick<EngineNode, 'name' | 'parameters'>>) => void;
  onDelete: () => void;
}

/**
 * A step's settings in a sheet beside the canvas: its name, the form its type generates and the same settings as JSON.
 * The sheet is not modal, so the canvas stays usable and clicking another step moves the sheet to it. Edits change the
 * editor's draft as they are made; the page's Save version saves them.
 */
export function StepSheet({ node, type, workflowId, steps, checks, order, readOnly, onClose, onMove, onChange, onDelete }: StepSheetProps) {
  const index = node ? order.indexOf(node.id) : -1;
  const errors = checks.filter((c) => c.level === 'error');
  const byField = Object.fromEntries(errors.filter((c) => c.field).map((c) => [c.field as string, c.message]));
  const look = groupLook(type?.group, node?.type);
  const trigger = type?.group === 'trigger';
  return (
    <DetailSheet
      open={!!node}
      onOpenChange={(o) => !o && onClose()}
      modal={false}
      // Starts at the canvas's top edge (--step-sheet-top, set by the editor) so Save version and Test run stay in view.
      widthClass="sm:max-w-xl sm:top-[var(--step-sheet-top,0px)] sm:h-[calc(100dvh-var(--step-sheet-top,0px))]"
      testId="step-sheet"
      scrollKey={node?.id}
      title={node ? node.name || type?.label || node.id : ''}
      description={type ? `${type.label} · ${type.description}` : node ? `${node.type} version ${node.typeVersion} · unknown type` : undefined}
      tags={
        node && (
          <>
            <Badge variant="outline" className={look.tile}>
              {KIND[type?.group ?? ''] ?? type?.group ?? 'Unknown'}
            </Badge>
            {type && type.effects !== 'none' && <Badge variant="outline">Effects: {type.effects}</Badge>}
            {errors.length > 0 && <Badge variant="destructive">{errors.length === 1 ? '1 error' : `${errors.length} errors`}</Badge>}
          </>
        )
      }
      navigation={
        index >= 0
          ? {
              currentIndex: index,
              totalCount: order.length,
              onPrev: index > 0 ? () => onMove(order[index - 1]) : undefined,
              onNext: index < order.length - 1 ? () => onMove(order[index + 1]) : undefined,
            }
          : undefined
      }
      footerActions={
        node &&
        !readOnly && (
          <Button type="button" variant="ghost" size="sm" className="text-destructive" onClick={onDelete} data-testid="definition-node-delete">
            <Trash2 /> Delete step
          </Button>
        )
      }
    >
      {node && (
        <fieldset disabled={readOnly} className="flex min-w-0 flex-col gap-5" data-testid="step-sheet-body">
          {errors.length > 0 && (
            <Alert variant="destructive" data-testid="step-sheet-errors">
              <AlertTriangle />
              <AlertTitle>This step stops the workflow from saving</AlertTitle>
              <AlertDescription>
                {errors.map((c, i) => (
                  <p key={`${c.code}-${i}`}>{c.message}</p>
                ))}
              </AlertDescription>
            </Alert>
          )}
          {trigger && node.type === EMAIL_TRIGGER && <EmailTriggerDetails parameters={node.parameters ?? {}} readOnly={readOnly} onConnected={(address) => onChange({ parameters: { ...(node.parameters ?? {}), mailbox: address } })} />}
          {trigger && node.type !== EMAIL_TRIGGER && <TriggerDetails workflowId={workflowId} schema={(node.parameters?.inputSchema ?? {}) as InputSchema} />}
          {/* Keyed by node id so moving to another step resets the field drafts. */}
          <StepFields key={node.id} node={node} type={type} steps={steps} errors={byField} onChange={onChange} />
        </fieldset>
      )}
    </DetailSheet>
  );
}

const EMAIL_TRIGGER = 'ops.trigger.email';

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
          <Link href={`/channels/email/${picked.id}`} className="ml-auto underline underline-offset-2">
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
              ['From here', 'Test run, with an email you type as JSON'],
            ]}
          />
        </Section>
      </div>
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>The mailbox isn’t listed?</span>
          <Button type="button" variant="outline" size="sm" onClick={() => setConnecting(true)} data-testid="trigger-connect-mailbox">
            <Plus className="size-4" /> Connect a mailbox
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

/** How a run of this workflow starts, and the input it must send. */
function TriggerDetails({ workflowId, schema }: { workflowId: string; schema: InputSchema }) {
  const fields = Object.entries(schema.properties ?? {});
  return (
    <>
      <div data-testid="trigger-how-it-starts">
      <Section title="How it starts" description="Every run of this workflow begins here.">
        <KeyValues
          rows={[
            [
              'From an app',
              <span>
                An authenticated call that starts a run, <code className="font-mono text-xs">POST /v1/runs</code>
              </span>,
            ],
            [
              'From an agent',
              <span>
                An agent that has this workflow as a tool, <code className="font-mono text-xs break-all">workflow__{workflowId}</code>
              </span>,
            ],
            ['From here', 'Test run, with an input you type'],
          ]}
        />
      </Section>
      </div>
      <div data-testid="trigger-run-input">
      <Section title="Run input" description="What a run must send; checked against the input schema before the first step.">
        {fields.length === 0 ? (
          <p className="text-sm text-muted-foreground">Any object: the input schema below names no fields.</p>
        ) : (
          <KeyValues
            rows={fields.map(([name, p]) => [
              name,
              <span className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="font-mono">
                  {p.type ?? 'any'}
                </Badge>
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

function StepFields({
  node,
  type,
  steps,
  errors,
  onChange,
}: {
  node: EngineNode;
  type: EngineNodeType | undefined;
  steps: StepRefs;
  errors: Record<string, string>;
  onChange: (patch: Partial<Pick<EngineNode, 'name' | 'parameters'>>) => void;
}) {
  const [text, setText] = React.useState(() => pretty(node.parameters));
  const [parseError, setParseError] = React.useState<string | undefined>();
  const lastSent = React.useRef(text);
  // A type with no form (an unknown type) can only be edited as JSON, so its settings start open.
  const [allOpen, setAllOpen] = React.useState(!type?.ui?.order.length);

  // Parameters changed outside this field (the form above, or a reload after save) replace the draft text.
  React.useEffect(() => {
    const next = pretty(node.parameters);
    if (next !== pretty(safeParse(lastSent.current))) {
      setText(next);
      lastSent.current = next;
      setParseError(undefined);
    }
  }, [node.parameters]);

  const edit = (value: string) => {
    setText(value);
    let parsed: unknown;
    try {
      parsed = value.trim() ? JSON.parse(value) : {};
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Not valid JSON');
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setParseError('Parameters must be a JSON object');
      return;
    }
    setParseError(undefined);
    lastSent.current = value;
    onChange({ parameters: parsed as Record<string, unknown> });
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <FormField id="definition-node-name" label="Name" optional>
        <Input id="definition-node-name" value={node.name ?? ''} placeholder={`e.g. ${type?.label ?? 'Review the refund'}`} onChange={(e) => onChange({ name: e.target.value || undefined })} />
      </FormField>
      {type?.ui?.order.length ? (
        <NodeSettingsForm form={type.ui} schema={type.parameters} value={node.parameters ?? {}} steps={steps} idPrefix={`node-${node.id}`} errors={errors} onChange={(parameters) => onChange({ parameters })} />
      ) : null}
      <Collapsible open={allOpen} onOpenChange={setAllOpen}>
        <CollapsibleTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="-ml-2 self-start" data-testid="definition-node-all-settings">
            <ChevronDown className={allOpen ? '' : '-rotate-90'} /> All settings
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="pt-2">
          <FormField id="definition-node-parameters" label="Parameters as JSON" hint="The same settings as the form above." error={parseError}>
            <Textarea
              id="definition-node-parameters"
              value={text}
              onChange={(e) => edit(e.target.value)}
              spellCheck={false}
              rows={12}
              className="font-mono text-xs"
              aria-invalid={parseError ? true : undefined}
              data-testid="definition-node-parameters"
            />
          </FormField>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

function safeParse(s: string): Record<string, unknown> | undefined {
  try {
    const v: unknown = JSON.parse(s);
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}
