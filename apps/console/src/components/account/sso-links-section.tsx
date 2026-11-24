'use client';

import { KeyRound, Link2, Unlink } from 'lucide-react';

import { QueryError } from '@/components/shared/query-states';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { relativeTime } from '@/lib/format';
import type { SsoLink } from '@/lib/auth';

/**
 * My security: the company providers the person can sign in with, each linked or not. Linking sends the browser to the
 * provider from this signed-in session; a provider's email alone never opens an existing account.
 */
export function SsoLinksSection({
  links,
  loading,
  error,
  retrying,
  onRetry,
  onLink,
  onUnlink,
  linkingId,
  linkError,
}: {
  links: SsoLink[] | undefined;
  loading: boolean;
  error: Error | null;
  retrying: boolean;
  onRetry: () => void;
  onLink: (link: SsoLink) => void;
  onUnlink: (link: SsoLink) => void;
  linkingId: string | null;
  linkError?: string;
}) {
  return (
    <SettingsSection title="Company sign-in" description="Link your account at your company’s provider to sign in with it. Signing in there with the same email never opens an account that is not linked.">
      <div className="flex flex-col gap-3" data-testid="sso-links">
        {linkError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive-text">{linkError}</p>}
        {loading ? (
          <Skeleton className="h-14 w-full" aria-busy="true" />
        ) : error ? (
          <QueryError what="your company sign-in" onRetry={onRetry} error={error} retrying={retrying} />
        ) : !links?.length ? (
          <p className="text-sm text-muted-foreground" data-testid="sso-links-none">
            Your workspace has no company sign-in for your email.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {links.map((l) => (
              <li key={l.providerId} className="flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2.5" data-testid="sso-link-row">
                <div className="flex min-w-0 items-center gap-3">
                  <KeyRound className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{l.label}</p>
                    <p className="text-xs text-muted-foreground">{l.linked ? `Linked${l.linkedAt ? ` ${relativeTime(l.linkedAt)}` : ''}` : 'Not linked'}</p>
                  </div>
                </div>
                {l.linked ? (
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">Linked</Badge>
                    <Button size="sm" variant="outline" onClick={() => onUnlink(l)} data-testid="unlink-sso">
                      <Unlink className="size-4" /> Unlink
                    </Button>
                  </div>
                ) : (
                  <LoadingButton size="sm" variant="outline" isLoading={linkingId === l.providerId} loadingText="Opening…" onClick={() => onLink(l)} data-testid="link-sso">
                    <Link2 className="size-4" /> Link {l.label}
                  </LoadingButton>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </SettingsSection>
  );
}
