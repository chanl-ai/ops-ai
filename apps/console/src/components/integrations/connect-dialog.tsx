'use client';

import * as React from 'react';
import { CheckCircle2, Eye, LogIn, PencilLine, ShieldCheck, Vault } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Stepper } from '@/components/shared/stepper';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { plural } from '@/lib/format';
import type { AuthMethod, CatalogSystem, ConnectInput, IntegrationKind } from '@/lib/types/integrations';
import { cn } from '@/lib/utils';

import { AUTH, SystemMark } from './integration-meta';
import { ScopePicker } from './scope-picker';

const STEPS = ['Sign-in', 'Scopes', 'Credential', 'Owner and expiry', 'Review'] as const;
const DESCRIBE = ['Which system and how the platform signs in', 'What the connection may read and write', 'How the gateway proves who it is', 'Who answers for it and when it ends', 'Check what it will be able to do'];
const VAULT_RE = /^vault:\/\/[a-z0-9][a-z0-9/_.-]+$/;
const LITERAL_RE = /^(sk[-_]|xox[abp]-|ghp_|eyJ|-----BEGIN|AKIA)|^[A-Za-z0-9+/=_-]{32,}$/;
const DAY = 86_400_000;
const ymd = (days: number) => new Date(Date.now() + days * DAY).toISOString().slice(0, 10);

/** Null when the reference is a usable vault path; otherwise what is wrong with it. */
export function vaultProblem(raw: string) {
  const v = raw.trim();
  if (!v) return 'Add the vault reference, e.g. vault://prod/integrations/servicenow/client-secret.';
  if (LITERAL_RE.test(v) && !v.startsWith('vault://')) return 'That looks like a secret. Paste the vault path that holds it, never the value.';
  if (!VAULT_RE.test(v)) return 'Use a vault path that starts with vault://, in lower case, e.g. vault://prod/integrations/servicenow/client-secret.';
  return null;
}

const consentBrand = (s: CatalogSystem) => (s.kind === 'm365' || s.kind === 'sharepoint' ? 'Microsoft' : s.kind === 'gdrive' ? 'Google' : s.name);

/**
 * Connect a bank system in five steps. Opened from a catalog card (system fixed), or from a source or tool module
 * dialog, where `kinds` limits the systems offered.
 */
export function ConnectDialog({
  open,
  onOpenChange,
  catalog,
  initialSystemId,
  kinds,
  teams,
  defaultTeam,
  currentUser,
  connecting,
  onConnect,
  modal,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: CatalogSystem[];
  initialSystemId?: string;
  kinds?: IntegrationKind[];
  teams: string[];
  defaultTeam: string;
  currentUser: string;
  connecting: boolean;
  onConnect: (input: ConnectInput) => Promise<unknown>;
  modal?: boolean;
}) {
  const choices = catalog.filter((c) => c.available && (!kinds || kinds.includes(c.kind)));
  const [step, setStep] = React.useState(1);
  const [systemId, setSystemId] = React.useState('');
  const [auth, setAuth] = React.useState<AuthMethod>('oauth_consent');
  const [name, setName] = React.useState('');
  const [instanceUrl, setInstanceUrl] = React.useState('');
  const [scopes, setScopes] = React.useState<string[]>([]);
  const [consent, setConsent] = React.useState<'none' | 'screen' | 'granting' | 'granted'>('none');
  const [credentialRef, setCredentialRef] = React.useState('');
  const [owner, setOwner] = React.useState('');
  const [expiry, setExpiry] = React.useState('');
  const [touched, setTouched] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);
  const system = catalog.find((c) => c.id === systemId);

  const pickSystem = React.useCallback(
    (sid: string) => {
      const s = catalog.find((c) => c.id === sid);
      setSystemId(sid);
      if (!s) return;
      setAuth(s.authMethods[0]);
      setName(s.connected ? `${s.name} · ${s.connected + 1}` : s.name);
      setInstanceUrl(s.instanceHint.startsWith('http') ? '' : `https://${s.instanceHint}`);
      // Reads start selected; writes are opt-in, so nothing can change data unless someone chose it.
      setScopes(s.scopes.filter((x) => x.access === 'read').map((x) => x.id));
      setConsent('none');
      setCredentialRef('');
      setExpiry(ymd(s.authMethods[0] === 'oauth_consent' ? 90 : 180));
    },
    [catalog],
  );

  React.useEffect(() => {
    if (!open) return;
    setStep(1);
    setTouched(false);
    setError(null);
    setOwner(defaultTeam);
    const first = initialSystemId ?? (choices.length === 1 ? choices[0].id : '');
    if (first) pickSystem(first);
    else {
      setSystemId('');
      setName('');
      setInstanceUrl('');
      setScopes([]);
    }
    // Re-runs once the catalog arrives, since a dialog opened from a source or module may load it on open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialSystemId, catalog.length > 0]);
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  const urlProblem = (() => {
    try {
      const u = new URL(instanceUrl.trim());
      return u.protocol === 'https:' ? null : 'Use an https address.';
    } catch {
      return 'Enter the full address, e.g. https://northfield.service-now.com.';
    }
  })();
  const credProblem = auth === 'oauth_consent' ? (consent === 'granted' ? null : 'Sign in and grant consent to continue.') : vaultProblem(credentialRef);
  const expiryProblem = !expiry ? 'Choose when the connection expires.' : new Date(`${expiry}T23:59:59`).getTime() <= Date.now() ? 'Choose a date after today.' : null;
  const stepErrors: Record<number, string | null> = {
    1: !system ? 'Choose the system to connect.' : !name.trim() ? 'Name the connection.' : urlProblem,
    2: scopes.length ? null : 'Grant at least one scope.',
    3: credProblem,
    4: !owner ? 'Choose the team that owns the connection.' : expiryProblem,
    5: null,
  };

  const next = () => {
    setTouched(true);
    if (stepErrors[step]) return;
    setTouched(false);
    setError(null);
    setStep(step + 1);
  };

  const finish = async () => {
    if (!system) return;
    setError(null);
    try {
      await onConnect({
        catalogId: system.id,
        name: name.trim(),
        instanceUrl: instanceUrl.trim(),
        authMethod: auth,
        scopes,
        credentialRef: auth === 'oauth_consent' ? undefined : credentialRef.trim(),
        consentBy: auth === 'oauth_consent' ? currentUser : undefined,
        ownerTeam: owner,
        expiresAt: new Date(`${expiry}T23:59:59`).toISOString(),
      });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const grant = () => {
    setConsent('granting');
    setTimeout(() => setConsent('granted'), 700);
  };

  const granted = system?.scopes.filter((s) => scopes.includes(s.id)) ?? [];
  const reads = granted.filter((s) => s.access === 'read');
  const writes = granted.filter((s) => s.access === 'write');
  const shownError = touched ? stepErrors[step] : null;

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !connecting && onOpenChange(o)}
      modal={modal}
      size="lg"
      title={system ? `Connect ${system.name}` : 'Connect a system'}
      description={`Step ${step} of ${STEPS.length} · ${DESCRIBE[step - 1]}`}
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="connect-stepper" />}
      bodyRef={bodyRef}
      panelClassName="h-[min(85vh,42rem)]"
      data-testid="connect-dialog"
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => (step === 1 ? onOpenChange(false) : (setTouched(false), setStep(step - 1)))} disabled={connecting}>
            {step === 1 ? 'Cancel' : 'Back'}
          </Button>
          {step < STEPS.length ? (
            <Button onClick={next}>Next</Button>
          ) : (
            <LoadingButton isLoading={connecting} loadingText="Connecting…" onClick={finish}>
              Connect
            </LoadingButton>
          )}
        </div>
      }
    >
      {(error || shownError) && <p className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error ?? shownError}</p>}

      {step === 1 && (
        <div className="flex flex-col gap-5">
          {initialSystemId && system ? (
            <div className="flex items-start gap-3 rounded-md border p-3">
              <SystemMark kind={system.kind} />
              <div className="min-w-0">
                <p className="text-sm font-medium">{system.name}</p>
                <p className="text-xs text-muted-foreground">{system.description}</p>
                <p className="pt-1 text-xs text-muted-foreground">Owned by {system.owner}, who approves later scope requests.</p>
              </div>
            </div>
          ) : (
            <FormField id="cx-system" label="System">
              <Select value={systemId} onValueChange={pickSystem}>
                <SelectTrigger id="cx-system" className="w-full">
                  <SelectValue placeholder="Choose a system" />
                </SelectTrigger>
                <SelectContent>
                  {choices.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
          {system && (
            <>
              <FormField id="cx-auth" label="Sign-in method" hint="Only the methods this system’s owner allows are offered.">
                <RadioGroup
                  value={auth}
                  onValueChange={(a) => {
                    setAuth(a as AuthMethod);
                    setConsent('none');
                    setExpiry(ymd(a === 'oauth_consent' ? 90 : 180));
                  }}
                  className="grid gap-2 sm:grid-cols-2"
                >
                  {system.authMethods.map((a, i) => (
                    <label key={a} htmlFor={`cx-auth-${a}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', auth === a && 'border-primary bg-primary/5')}>
                      <RadioGroupItem value={a} id={`cx-auth-${a}`} className="mt-0.5" />
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">
                          {AUTH[a].label}
                          {i === 0 && system.authMethods.length > 1 && <span className="ml-1.5 text-xs font-normal text-muted-foreground">Recommended</span>}
                        </span>
                        <span className="block text-xs text-muted-foreground">{AUTH[a].hint}</span>
                      </span>
                    </label>
                  ))}
                </RadioGroup>
              </FormField>
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField id="cx-name" label="Connection name" error={touched && !name.trim() ? 'Name the connection.' : undefined} hint="Shown on every source, module and mailbox that uses it.">
                  <Input id="cx-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ServiceNow · operations desk" aria-invalid={touched && !name.trim()} />
                </FormField>
                <FormField id="cx-url" label="Tenant or instance URL" error={touched && name.trim() ? (urlProblem ?? undefined) : undefined}>
                  <Input id="cx-url" value={instanceUrl} onChange={(e) => setInstanceUrl(e.target.value)} placeholder={`e.g. https://${system.instanceHint.replace(/^https?:\/\//, '')}`} className="font-mono text-sm" aria-invalid={touched && !!urlProblem} />
                </FormField>
              </div>
            </>
          )}
        </div>
      )}

      {step === 2 && system && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">Grant only what the sources and tools on this connection need. Reads are selected; writes are opt-in. More can be requested later from the connection’s Scopes tab.</p>
          <ScopePicker
            scopes={system.scopes}
            selected={scopes}
            onChange={(s) => {
              setScopes(s);
              // Consent covers the exact scopes shown on the consent screen, so changing them asks again.
              if (consent === 'granted') setConsent('none');
            }}
          />
        </div>
      )}

      {step === 3 && system && (
        <div className="flex flex-col gap-4">
          {auth === 'oauth_consent' ? (
            consent === 'granted' ? (
              <div className="flex items-start gap-3 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3" data-testid="consent-granted">
                <CheckCircle2 className="mt-0.5 size-4 text-emerald-600" />
                <div className="min-w-0 flex-1 text-sm">
                  <p className="font-medium">Consent granted by {currentUser}</p>
                  <p className="text-xs text-muted-foreground">
                    {plural(scopes.length, 'scope')} on {instanceUrl.replace(/^https?:\/\//, '')}. The refresh token is stored in the bank vault; nobody sees it.
                  </p>
                </div>
                <Button size="sm" variant="ghost" onClick={() => setConsent('screen')}>
                  Sign in again
                </Button>
              </div>
            ) : consent === 'none' ? (
              <div className="flex flex-col items-start gap-3 rounded-md border p-4">
                <p className="text-sm text-muted-foreground">An administrator of {system.name} signs in and approves the {plural(scopes.length, 'scope')} you chose. Nothing is connected until you finish.</p>
                <Button
                  onClick={() => {
                    setTouched(false);
                    setConsent('screen');
                  }}
                  data-testid="oauth-sign-in"
                >
                  <LogIn className="size-4" /> Sign in with {consentBrand(system)}
                </Button>
              </div>
            ) : (
              <div className="mx-auto flex w-full max-w-md flex-col gap-3 rounded-lg border bg-card p-5 shadow-sm" role="group" aria-label={`${consentBrand(system)} consent screen`} data-testid="consent-screen">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <SystemMark kind={system.kind} size="sm" /> {consentBrand(system)} · {instanceUrl.replace(/^https?:\/\//, '')}
                </div>
                <p className="text-base font-semibold">Permissions requested</p>
                <p className="text-sm">
                  <span className="font-medium">Northfield Ops AI</span> wants to:
                </p>
                <ul className="flex flex-col gap-1.5 text-sm">
                  {granted.map((s) => (
                    <li key={s.id} className="flex items-start gap-2">
                      {s.access === 'write' ? <PencilLine className="mt-0.5 size-3.5 shrink-0 text-amber-600" /> : <Eye className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
                      <span>{s.label}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">Signed in as {currentUser}. Accepting grants these for the whole organisation until the expiry you set.</p>
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="outline" disabled={consent === 'granting'} onClick={() => setConsent('none')}>
                    Cancel
                  </Button>
                  <LoadingButton size="sm" isLoading={consent === 'granting'} loadingText="Granting…" onClick={grant} data-testid="consent-accept">
                    Accept
                  </LoadingButton>
                </div>
              </div>
            )
          ) : (
            <>
              <Alert>
                <Vault className="size-4" />
                <AlertDescription>
                  {AUTH[auth].hint} The gateway resolves the reference on each call; agents, workers and this console never see the value.
                </AlertDescription>
              </Alert>
              <FormField id="cx-cred" label="Vault reference" error={touched ? (credProblem ?? undefined) : undefined} hint="The path in the bank vault, not the secret itself.">
                <Input id="cx-cred" value={credentialRef} onChange={(e) => setCredentialRef(e.target.value)} placeholder={`e.g. vault://prod/integrations/${system.id.replace('cat_', '').replace(/_/g, '-')}/${auth === 'api_key' ? 'api-key' : auth === 'mtls' ? 'client-certificate' : 'client-secret'}`} className="font-mono text-sm" aria-invalid={touched && !!credProblem} autoComplete="off" spellCheck={false} />
              </FormField>
            </>
          )}
        </div>
      )}

      {step === 4 && (
        <div className="flex flex-col gap-5">
          <FormField id="cx-owner" label="Owner team" hint="Answers for the connection: renewals, scope requests and incidents.">
            <Select value={owner} onValueChange={setOwner}>
              <SelectTrigger id="cx-owner" className="w-full">
                <SelectValue placeholder="Choose a team" />
              </SelectTrigger>
              <SelectContent>
                {teams.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="cx-expiry" label={auth === 'oauth_consent' ? 'Consent expires' : 'Credential expires'} error={touched ? (expiryProblem ?? undefined) : undefined} hint="The owner team is reminded 30 days before. After it, every dependant stops until someone reconnects.">
            <div className="flex flex-wrap items-center gap-2">
              <Input id="cx-expiry" type="date" value={expiry} min={ymd(1)} onChange={(e) => setExpiry(e.target.value)} className="w-44" aria-invalid={touched && !!expiryProblem} />
              {[30, 90, 180, 365].map((d) => (
                <Button key={d} type="button" size="sm" variant={expiry === ymd(d) ? 'secondary' : 'ghost'} onClick={() => setExpiry(ymd(d))}>
                  {d} days
                </Button>
              ))}
            </div>
          </FormField>
        </div>
      )}

      {step === 5 && system && (
        <div className="flex flex-col gap-4" data-testid="connect-review">
          <ReviewRow label="System" value={`${system.name} · ${AUTH[auth].label}`} detail={`${name} · ${instanceUrl}`} onEdit={() => setStep(1)} />
          <ReviewRow
            label="Credential"
            value={auth === 'oauth_consent' ? `Consent granted by ${currentUser}` : credentialRef}
            mono={auth !== 'oauth_consent'}
            onEdit={() => setStep(3)}
          />
          <ReviewRow label="Owner and expiry" value={owner} detail={`Expires ${new Date(`${expiry}T12:00:00`).toLocaleDateString('en-CA', { dateStyle: 'medium' })}`} onEdit={() => setStep(4)} />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-md border p-3">
              <p className="flex items-center gap-1.5 text-sm font-medium">
                <Eye className="size-4 text-muted-foreground" /> It will be able to read
              </p>
              <ul className="mt-2 flex flex-col gap-1.5 text-sm">
                {reads.length ? reads.map((s) => <li key={s.id}>{s.label}<span className="block text-xs text-muted-foreground">{s.description}</span></li>) : <li className="text-muted-foreground">Nothing</li>}
              </ul>
            </div>
            <div className={cn('rounded-md border p-3', writes.length && 'border-amber-500/40')}>
              <p className="flex items-center gap-1.5 text-sm font-medium">
                <PencilLine className="size-4 text-amber-600" /> It will be able to write
              </p>
              <ul className="mt-2 flex flex-col gap-1.5 text-sm">
                {writes.length ? writes.map((s) => <li key={s.id}>{s.label}<span className="block text-xs text-muted-foreground">{s.description}</span></li>) : <li className="text-muted-foreground">Nothing. It is read only.</li>}
              </ul>
            </div>
          </div>
          <Button variant="link" size="sm" className="self-start px-0" onClick={() => setStep(2)}>
            Change scopes
          </Button>
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-3.5 shrink-0" /> Connecting is recorded in the audit log. Sources, tool modules and mailboxes can then pick this connection; workflows still need their own approvals.
          </p>
        </div>
      )}
    </DialogShell>
  );
}

function ReviewRow({ label, value, detail, mono, onEdit }: { label: string; value: string; detail?: string; mono?: boolean; onEdit: () => void }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border px-3 py-2.5">
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn('truncate text-sm font-medium', mono && 'font-mono text-xs')}>{value}</p>
        {detail && <p className="truncate text-xs text-muted-foreground">{detail}</p>}
      </div>
      <Button size="sm" variant="ghost" onClick={onEdit}>
        Edit
      </Button>
    </div>
  );
}
