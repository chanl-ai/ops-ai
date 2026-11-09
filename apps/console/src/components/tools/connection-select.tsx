'use client';

import Link from 'next/link';
import { Plus } from 'lucide-react';

import { IntegrationStatusBadge, SystemMark } from '@/components/integrations/integration-meta';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ConnectionRef, IntegrationKind, IntegrationStatus } from '@/lib/types/integrations';
import { appPageHref } from '@/lib/app-links';

/** A connection as the picker lists it; `kind` draws its system's mark where the caller knows it. */
export type ConnectionOption = { id: string; name: string; status: IntegrationStatus; kind?: IntegrationKind };

/**
 * The connection a module signs in through, picked from the team's connections, with a way to make a new one. The
 * module page's Connection tab and a REST tool's page show this same picker.
 */
export function ConnectionSelect({
  value,
  options,
  loading,
  disabled,
  onChange,
  className,
}: {
  value?: Pick<ConnectionRef, 'id' | 'name'> | null;
  /** The team's connections; a revoked one is offered only while it is the module's. */
  options?: ConnectionOption[];
  loading?: boolean;
  disabled?: boolean;
  onChange: (connectionId: string) => void;
  className?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={value?.id ?? ''} onValueChange={onChange} disabled={disabled || loading}>
        <SelectTrigger className={className ?? 'min-w-64'} aria-label="App" data-testid="module-connection-select">
          <SelectValue placeholder={loading ? 'Loading apps…' : 'No app yet'} />
        </SelectTrigger>
        <SelectContent>
          {(options ?? [])
            .filter((c) => c.status !== 'revoked' || c.id === value?.id)
            .map((c) => (
              <SelectItem key={c.id} value={c.id}>
                <span className="flex items-center gap-2">
                  {c.kind && <SystemMark kind={c.kind} size="sm" />} {c.name}
                  {c.status !== 'healthy' && <IntegrationStatusBadge status={c.status} />}
                </span>
              </SelectItem>
            ))}
        </SelectContent>
      </Select>
      <Button variant="outline" size="sm" asChild>
        <Link href="/integrations?new=1" data-testid="new-connection">
          <Plus className="size-4" /> Add custom app
        </Link>
      </Button>
      {value && (
        <Button variant="ghost" size="sm" asChild>
          <Link href={appPageHref(value.id)}>Open app</Link>
        </Button>
      )}
    </div>
  );
}
