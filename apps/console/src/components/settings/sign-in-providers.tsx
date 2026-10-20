'use client';

import { CheckCircle2, Clock, Pencil, Plus, Trash2 } from 'lucide-react';

import { KIND_LABEL, ROLE_LABEL } from '@/components/settings/sign-in-provider-dialog';
import { CopyField } from '@/components/shared/setting/copy-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { relativeTime } from '@/lib/format';
import type { SignInProvider } from '@/lib/types/sign-in';

/** A domain's state: verified routes people to the provider, pending routes nobody yet. */
function DomainBadge({ verifiedAt }: { verifiedAt: string | null }) {
  return verifiedAt ? (
    <Badge variant="secondary" className="gap-1 font-normal">
      <CheckCircle2 className="size-3" /> Verified
    </Badge>
  ) : (
    <Badge variant="outline" className="gap-1 font-normal">
      <Clock className="size-3" /> Pending
    </Badge>
  );
}

/** The workspace's providers: what the sign-in page offers, and to which domains. */
export function SignInProvidersSection({ providers, teamName, onAdd, onEdit, onRemove }: { providers: SignInProvider[]; teamName: (id: string) => string; onAdd: () => void; onEdit: (p: SignInProvider) => void; onRemove: (p: SignInProvider) => void }) {
  return (
    <SettingsSection title="Providers" description="How people sign in. An email on a verified domain goes to that domain’s provider; everyone else uses a password while the password provider is on, or when no provider is on at all.">
      <div className="flex flex-col gap-3">
        <div className="overflow-x-auto rounded-md border bg-card">
          <Table data-testid="sign-in-providers">
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Domains</TableHead>
                <TableHead>New people</TableHead>
                <TableHead className="w-20" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-6 text-center text-sm text-muted-foreground">
                    No providers yet, so everyone signs in with a password.
                  </TableCell>
                </TableRow>
              )}
              {providers.map((p) => (
                <TableRow key={p.id} data-testid={`provider-${p.id}`}>
                  <TableCell>
                    <div className="flex min-w-40 flex-col">
                      <span className="font-medium">{p.label}</span>
                      <span className="text-xs text-muted-foreground">{KIND_LABEL[p.kind]}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={p.enabled ? 'secondary' : 'outline'}>{p.enabled ? 'On' : 'Off'}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {p.verification.length ? p.verification.map((c) => <Badge key={c.domain} variant={c.verifiedAt ? 'secondary' : 'outline'} className="font-normal">{c.domain}{c.verifiedAt ? '' : ' (pending)'}</Badge>) : <span className="text-sm text-muted-foreground">{p.kind === 'password' ? 'Everyone else' : 'None'}</span>}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm whitespace-nowrap text-muted-foreground">{p.jit ? `${ROLE_LABEL[p.jit.role]} in ${p.jit.team ? teamName(p.jit.team) : 'the default team'}` : '—'}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon" aria-label={`Edit ${p.label}`} onClick={() => onEdit(p)}>
                        <Pencil className="size-4" />
                      </Button>
                      <Button variant="ghost" size="icon" aria-label={`Delete ${p.label}`} onClick={() => onRemove(p)}>
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <Button size="sm" variant="outline" className="self-start" onClick={onAdd} data-testid="add-provider">
          <Plus className="size-4" /> Add provider
        </Button>
      </div>
    </SettingsSection>
  );
}

/** Every listed domain with the TXT record that proves it and a Verify for the ones still pending. */
export function SignInDomainsSection({ providers, verifying, onVerify }: { providers: SignInProvider[]; verifying: string | null; onVerify: (domain: string) => void }) {
  const rows = providers.flatMap((p) => p.verification.map((c) => ({ ...c, provider: p.label })));
  return (
    <SettingsSection title="Domains" description="Publish each domain’s TXT record in your DNS, then verify it. Until then the domain signs nobody in, so no other workspace can take your people by listing it.">
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No domains yet. Add one to a provider to get its TXT record.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border bg-card">
          <Table data-testid="sign-in-domains">
            <TableHeader>
              <TableRow>
                <TableHead>Domain</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="min-w-80">TXT record</TableHead>
                <TableHead className="w-28" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((c) => (
                <TableRow key={c.domain} data-testid={`domain-${c.domain}`}>
                  <TableCell>
                    <div className="flex flex-col">
                      <span className="font-medium">{c.domain}</span>
                      <span className="text-xs text-muted-foreground">{c.provider}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <DomainBadge verifiedAt={c.verifiedAt} />
                      {c.verifiedAt && <span className="text-xs text-muted-foreground">{relativeTime(c.verifiedAt)}</span>}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">Name {c.record.name}, type TXT, value:</span>
                      <CopyField value={c.record.value} label={`TXT value for ${c.domain}`} />
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    {!c.verifiedAt && (
                      <LoadingButton size="sm" variant="outline" isLoading={verifying === c.domain} onClick={() => onVerify(c.domain)} data-testid={`verify-${c.domain}`}>
                        Verify
                      </LoadingButton>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </SettingsSection>
  );
}
