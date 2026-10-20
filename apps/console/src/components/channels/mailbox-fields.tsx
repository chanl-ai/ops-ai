'use client';

import * as React from 'react';
import { CheckCircle2, KeyRound, Plug, XCircle } from 'lucide-react';

import { SecretDialog } from '@/components/settings/secret-dialog';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Combobox } from '@/components/shared/setting/pickers';
import { StepList } from '@/components/shared/step-list';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { useTestMailbox } from '@/hooks/channels-queries';
import { useSecrets } from '@/hooks/secrets-queries';
import type { MailProvider, Mailbox, MailboxInput, MailboxTest, ReplySender } from '@/lib/types/channels';

/** The connect form's providers. */
export const PROVIDERS: { value: MailProvider; title: string; description: string; disabled?: boolean }[] = [
  { value: 'gmail', title: 'Gmail', description: 'IMAP with an app password. Turn on two-step verification in the Google account first.' },
  { value: 'imap', title: 'Other IMAP', description: 'Any server that speaks IMAP over TLS, with a user name and password.' },
  { value: 'graph', title: 'Microsoft 365', description: 'Reads through Microsoft Graph with an app registration: its tenant id, client id and a client secret.' },
];
export const PROVIDER_LABEL: Record<MailProvider, string> = { gmail: 'Gmail', imap: 'IMAP', graph: 'Microsoft 365' };

/** The form as typed: strings for every text field, converted to a `MailboxInput` on save. */
export interface MailboxForm {
  provider: MailProvider;
  name: string;
  address: string;
  host: string;
  port: string;
  tls: boolean;
  username: string;
  secret: string | null;
  graphTenantId: string;
  graphClientId: string;
  folder: string;
  sender: ReplySender;
  fromAddress: string;
  smtpHost: string;
  smtpPort: string;
  smtpStarttls: boolean;
  senderSecret: string | null;
}
export type MailboxErrors = Partial<Record<'name' | 'address' | 'host' | 'port' | 'secret' | 'graphTenantId' | 'graphClientId' | 'folder' | 'fromAddress' | 'smtpHost' | 'smtpPort' | 'senderSecret', string>>;

/** How replies leave. Gmail fills its own SMTP server, so its SMTP sender needs only the from address and secret. */
export const SENDERS: { value: ReplySender; title: string; description: string }[] = [
  { value: 'none', title: 'No replies', description: 'Workflows read this mailbox but do not answer from it.' },
  { value: 'smtp', title: 'SMTP', description: 'The bank’s own mail server, or Gmail’s with the same app password.' },
  { value: 'resend', title: 'Resend', description: 'A sending service, with an API key kept in Secrets.' },
];
/** A Microsoft 365 mailbox can answer from itself through Graph, with the app registration it reads with. */
const GRAPH_SENDER = { value: 'graph' as const, title: 'Microsoft 365', description: 'Replies leave from this mailbox through Microsoft Graph; nothing more to set.' };

export const blankForm = (provider: MailProvider): MailboxForm => ({ provider, name: '', address: '', host: '', port: '', tls: true, username: '', secret: null, graphTenantId: '', graphClientId: '', folder: 'inbox', sender: 'none', fromAddress: '', smtpHost: '', smtpPort: '', smtpStarttls: true, senderSecret: null });

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The checks Connect and Save run before anything is sent; the server checks again. */
export function checkMailbox(v: MailboxForm): MailboxErrors {
  const e: MailboxErrors = {};
  if (!v.name.trim()) e.name = 'Name it so the team can tell mailboxes apart.';
  if (!EMAIL.test(v.address.trim())) e.address = 'Enter the mailbox’s address.';
  if (v.provider === 'imap' && !v.host.trim()) e.host = 'Enter the IMAP server.';
  if (v.provider === 'graph' && !/^[A-Za-z0-9.-]+$/.test(v.graphTenantId.trim())) e.graphTenantId = 'Enter the Microsoft tenant id, e.g. bank.onmicrosoft.com.';
  if (v.provider === 'graph' && !/^[A-Za-z0-9-]+$/.test(v.graphClientId.trim())) e.graphClientId = 'Enter the app registration’s client id.';
  if (v.port.trim() && !/^\d{1,5}$/.test(v.port.trim())) e.port = 'Enter a port number, e.g. 993.';
  if (!v.secret) e.secret = 'Pick the secret that holds it, or add one.';
  if (!v.folder.trim()) e.folder = 'Enter the folder to watch, e.g. inbox.';
  if (v.sender === 'smtp' || v.sender === 'resend') {
    if (!EMAIL.test(v.fromAddress.trim())) e.fromAddress = 'Enter the address replies come from.';
    if (!v.senderSecret) e.senderSecret = 'Pick the secret that holds it, or add one.';
  }
  if (v.sender === 'smtp' && v.provider !== 'gmail' && !v.smtpHost.trim()) e.smtpHost = 'Enter the SMTP server.';
  if (v.smtpPort.trim() && !/^\d{1,5}$/.test(v.smtpPort.trim())) e.smtpPort = 'Enter a port number, e.g. 587.';
  return e;
}

export function toInput(v: MailboxForm): MailboxInput {
  const imap = v.provider === 'imap';
  const graph = v.provider === 'graph';
  // Graph sends from the mailbox it reads; SMTP and Resend name their own from address and secret.
  const ownSender = v.sender === 'smtp' || v.sender === 'resend';
  return {
    name: v.name.trim(),
    address: v.address.trim(),
    provider: v.provider,
    imapHost: imap ? v.host.trim() : null,
    imapPort: imap && v.port.trim() ? Number(v.port.trim()) : null,
    imapTls: imap ? v.tls : true,
    username: graph ? null : v.username.trim() || null,
    passwordSecret: v.secret,
    graphTenantId: graph ? v.graphTenantId.trim() : null,
    graphClientId: graph ? v.graphClientId.trim() : null,
    folder: v.folder.trim(),
    sender: v.sender,
    fromAddress: ownSender ? v.fromAddress.trim() || null : null,
    smtpHost: v.sender === 'smtp' ? v.smtpHost.trim() || null : null,
    smtpPort: v.sender === 'smtp' && v.smtpPort.trim() ? Number(v.smtpPort.trim()) : null,
    smtpStarttls: v.smtpStarttls,
    senderSecret: ownSender ? v.senderSecret : null,
  };
}

/** A secret named by reference: pick one from the Secrets list or add one; the value is never typed here. */
function SecretPicker({ id, value, onChange }: { id: string; value: string | null; onChange: (name: string) => void }) {
  const secrets = useSecrets();
  const [adding, setAdding] = React.useState(false);
  const options = (secrets.data ?? []).map((s) => ({ value: s.name, label: s.name, hint: s.teams?.length ? s.teams.join(', ') : 'Every team' }));
  return (
    <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
      <div className="min-w-0 flex-1">
        <Combobox id={id} options={options} value={value} onChange={onChange} noun="secrets" placeholder={secrets.isLoading ? 'Loading secrets…' : 'Choose a secret'} />
      </div>
      <Button type="button" variant="outline" onClick={() => setAdding(true)} data-testid={`${id}-add`}>
        <KeyRound className="size-4" /> Add secret
      </Button>
      {/* Rendered here, outside the mailbox form's submit: a dialog's submit would otherwise reach the outer form. */}
      <SecretDialog open={adding} rotating={null} onOpenChange={setAdding} onSaved={(name) => (onChange(name), setAdding(false))} />
    </div>
  );
}

/** Test connection: tools-service signs in with the secret and reads the folder's newest message, unread. */
function TestConnection({ target }: { target: () => { input: MailboxInput } | { id: string } | null }) {
  const test = useTestMailbox();
  const [result, setResult] = React.useState<MailboxTest | null>(null);
  const run = async () => {
    const t = target();
    if (!t) return;
    setResult(null);
    try {
      setResult(await test.mutateAsync(t));
    } catch (e) {
      setResult({ ok: false, steps: [], newest: null, error: e instanceof Error ? e.message : 'The test could not run.' });
    }
  };
  return (
    <div className="flex flex-col gap-3" data-testid="mailbox-test">
      <div className="flex flex-wrap items-center gap-3">
        <LoadingButton type="button" variant="outline" onClick={run} isLoading={test.isPending} loadingText="Testing…" data-testid="mailbox-test-run">
          <Plug className="size-4" /> Test connection
        </LoadingButton>
        <span className="text-xs text-muted-foreground">Signs in and reads the folder without marking anything read.</span>
      </div>
      {result && result.steps.length > 0 && <StepList title="Connection test" steps={result.steps.map((s) => ({ title: s.title, state: s.state === 'skipped' ? 'pending' : s.state }))} />}
      {result && (
        <Alert variant={result.ok ? 'default' : 'destructive'} data-testid="mailbox-test-result" data-ok={result.ok}>
          {result.ok ? <CheckCircle2 className="text-success-text" /> : <XCircle />}
          <AlertTitle>{result.ok ? 'Connected' : 'Could not connect'}</AlertTitle>
          <AlertDescription>{result.ok ? (result.newest ? `Newest: “${result.newest.subject}” from ${result.newest.from}` : 'The folder is empty.') : result.error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/**
 * A mailbox's sign-in settings, the folder it watches and a test. One component for the connect page, the connect
 * dialog on the trigger sheet and a mailbox's settings. `testTarget` gives what Test connection checks: the unsaved
 * form, or the saved mailbox.
 */
export function MailboxFields({ value, onChange, errors, idPrefix, testTarget }: { value: MailboxForm; onChange: (patch: Partial<MailboxForm>) => void; errors: MailboxErrors; idPrefix: string; testTarget: () => { input: MailboxInput } | { id: string } | null }) {
  const id = (f: string) => `${idPrefix}-${f}`;
  const text = (field: 'name' | 'address' | 'host' | 'port' | 'graphTenantId' | 'graphClientId' | 'folder' | 'fromAddress' | 'smtpHost' | 'smtpPort', label: string, placeholder: string, hint?: string) => (
    <FormField id={id(field)} label={label} hint={hint} error={errors[field]}>
      <Input id={id(field)} value={value[field]} onChange={(e) => onChange({ [field]: e.target.value })} placeholder={placeholder} className="bg-card" autoComplete="off" aria-invalid={!!errors[field]} />
    </FormField>
  );
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="mailbox-fields">
      {text('name', 'Name', 'e.g. Levy notices', 'Shown in the trigger’s mailbox picker.')}
      {text('address', 'Mailbox address', value.provider === 'gmail' ? 'e.g. intake.test@gmail.com' : 'e.g. intake@bank.example')}
      {value.provider === 'imap' && (
        <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          {text('host', 'IMAP server', 'e.g. mail.bank.example', 'The server must be an allowed host on the Egress page.')}
          {text('port', 'Port', 'e.g. 993')}
        </div>
      )}
      {value.provider === 'imap' && (
        <FormField id={id('tls')} label="Use TLS" hint="Plain IMAP sends the password in clear and is refused outside a dev stack.">
          <Switch id={id('tls')} checked={value.tls} onCheckedChange={(tls) => onChange({ tls })} />
        </FormField>
      )}
      {value.provider === 'graph' ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {text('graphTenantId', 'Microsoft tenant id', 'e.g. bank.onmicrosoft.com', 'The tenant the app registration belongs to.')}
          {text('graphClientId', 'Client id', 'e.g. 00000000-0000-0000-0000-000000000000', 'The app registration’s application (client) id.')}
        </div>
      ) : (
        <FormField id={id('username')} label="User name" optional hint="Leave empty to sign in with the address.">
          <Input id={id('username')} value={value.username} onChange={(e) => onChange({ username: e.target.value })} placeholder="e.g. intake" className="bg-card" autoComplete="off" />
        </FormField>
      )}
      <FormField id={id('secret')} label={value.provider === 'gmail' ? 'App password' : value.provider === 'graph' ? 'Client secret' : 'Password'} error={errors.secret} hint="A secret on the Secrets page. Only the tools service reads it, when it reads the mailbox.">
        <SecretPicker id={id('secret')} value={value.secret} onChange={(secret) => onChange({ secret })} />
      </FormField>
      {text('folder', 'Folder', 'e.g. inbox', 'New mail here starts runs. Mail already in it when a workflow goes live starts nothing.')}
      <TestConnection target={testTarget} />
      <Separator />
      <section className="flex flex-col gap-4" aria-labelledby={id('replies')} data-testid="mailbox-replies">
        <h3 id={id('replies')} className="text-sm font-semibold">
          Replies
        </h3>
        <ChoiceCards name={id('sender')} label="Send replies with" choices={value.provider === 'graph' ? [...SENDERS, GRAPH_SENDER] : SENDERS} value={value.sender} onChange={(s) => onChange({ sender: s as ReplySender, fromAddress: value.fromAddress || value.address })} />
        {(value.sender === 'smtp' || value.sender === 'resend') && text('fromAddress', 'From address', 'e.g. intake@bank.example', 'Replies a workflow sends from this mailbox come from this address.')}
        {value.sender === 'smtp' && value.provider !== 'gmail' && (
          <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            {text('smtpHost', 'SMTP server', 'e.g. smtp.bank.example', 'The server must be an allowed host on the Egress page.')}
            {text('smtpPort', 'Port', 'e.g. 587')}
          </div>
        )}
        {value.sender === 'smtp' && value.provider === 'gmail' && <p className="text-sm text-muted-foreground">Sends through Gmail’s SMTP server with the app password below.</p>}
        {(value.sender === 'smtp' || value.sender === 'resend') && (
          <FormField id={id('senderSecret')} label={value.sender === 'resend' ? 'API key' : 'SMTP password'} error={errors.senderSecret} hint="A secret on the Secrets page, read only when a reply is sent.">
            <SecretPicker id={id('senderSecret')} value={value.senderSecret} onChange={(senderSecret) => onChange({ senderSecret })} />
          </FormField>
        )}
      </section>
    </div>
  );
}

export const formOf = (m: Mailbox): MailboxForm => ({
  provider: m.provider,
  name: m.name,
  address: m.address,
  host: m.imapHost ?? '',
  port: m.imapPort ? String(m.imapPort) : '',
  tls: m.imapTls,
  username: m.username ?? '',
  secret: m.passwordSecret,
  graphTenantId: m.graphTenantId ?? '',
  graphClientId: m.graphClientId ?? '',
  folder: m.folder,
  sender: m.sender,
  fromAddress: m.fromAddress ?? '',
  smtpHost: m.smtpHost ?? '',
  smtpPort: m.smtpPort ? String(m.smtpPort) : '',
  smtpStarttls: m.smtpStarttls,
  senderSecret: m.senderSecret,
});
