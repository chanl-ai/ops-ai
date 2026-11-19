'use client';

import Link from 'next/link';
import { Plus } from 'lucide-react';

import { IntegrationStatusBadge } from '@/components/integrations/integration-meta';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/shared/search-select';
import { connectionOptions } from '@/hooks/options-queries';
import type { ConnectionRef, IntegrationStatus } from '@/lib/types/integrations';
import { appPageHref } from '@/lib/app-links';

/**
 * The connection a module signs in through, searched on the server as the person types, with a way to make a new one.
 * The module page's Connection tab and a REST tool's page show this same picker. A revoked connection is offered only
 * while it is the module's.
 */
export function ConnectionSelect({
  value,
  disabled,
  onChange,
  className,
}: {
  value?: Pick<ConnectionRef, 'id' | 'name'> | null;
  disabled?: boolean;
  onChange: (connectionId: string, name?: string) => void;
  className?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchSelect
        source={connectionOptions}
        value={value?.id ? { id: value.id, label: value.name } : null}
        onChange={(id, o) => onChange(id, o?.label)}
        placeholder="No app yet"
        searchPlaceholder="Search apps"
        emptyText="No app matches."
        ariaLabel="App"
        disabled={disabled}
        className={className ?? 'min-w-64'}
        testId="module-connection-select"
        renderOption={(o) => (
          <span className="flex items-center gap-2">
            {o.label}
            {o.status !== 'healthy' && <IntegrationStatusBadge status={o.status as IntegrationStatus} />}
          </span>
        )}
      />
      <Button variant="outline" size="sm" asChild>
        <Link href="/data/connectors?new=1" data-testid="new-connection">
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
