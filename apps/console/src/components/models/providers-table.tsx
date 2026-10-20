'use client';

import { AlertTriangle, CheckCircle2, CircleDashed, Cpu, KeyRound, PlugZap, XCircle } from 'lucide-react';

import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { relativeTime } from '@/lib/format';
import type { ModelProvider } from '@/lib/types/models';

import { PROVIDER_TYPES } from './provider-meta';

/** The last test, as a person reads it: answering, refusing (with the provider's own reason), or never tried. */
function Health({ provider }: { provider: ModelProvider }) {
  const h = provider.health;
  if (!provider.keySet && provider.keySecret)
    return (
      <span className="flex items-center gap-1.5 text-destructive">
        <AlertTriangle className="size-3.5" /> No key saved
      </span>
    );
  if (h.status === 'untested')
    return (
      <span className="flex items-center gap-1.5">
        <CircleDashed className="size-3.5" /> Not tested
      </span>
    );
  return h.status === 'ok' ? (
    <span className="flex items-center gap-1.5 text-success-text">
      <CheckCircle2 className="size-3.5" /> Answering in {h.latencyMs} ms · {h.models} models · tested {relativeTime(h.at ?? undefined)}
    </span>
  ) : (
    <span className="flex items-center gap-1.5 text-destructive">
      <XCircle className="size-3.5" /> Refusing: {h.error} · {relativeTime(h.at ?? undefined)}
    </span>
  );
}

/** The workspace's model providers: the key each one signs in with, whether it answers, and what routes to it. */
export function ProvidersTable({ providers, testing, onTest, onChangeKey }: { providers: ModelProvider[]; testing: string | null; onTest: (p: ModelProvider) => void; onChangeKey: (p: ModelProvider) => void }) {
  if (!providers.length) return <p className="rounded-md border bg-card py-6 text-center text-sm text-muted-foreground">No provider yet, so no agent or workflow can call a model. Connect one to start.</p>;
  return (
    <Rows className="rounded-md border bg-card" testId="model-providers">
      {providers.map((p) => (
        <Row
          key={p.id}
          wrap
          leading={
            <div className="flex size-8 items-center justify-center rounded-md bg-muted">
              <Cpu className="size-4 text-muted-foreground" />
            </div>
          }
          title={
            <span className="flex flex-wrap items-center gap-2">
              {p.name}
              <Badge variant="outline" className="font-normal">
                {PROVIDER_TYPES[p.type].label}
              </Badge>
            </span>
          }
          description={<span className="font-mono">{p.baseUrl}</span>}
          trailing={
            <>
              <LoadingButton size="sm" variant="outline" isLoading={testing === p.id} loadingText="Testing…" onClick={() => onTest(p)} disabled={!p.keySet} data-testid={`provider-test-${p.id}`}>
                <PlugZap className="size-3.5" /> Test
              </LoadingButton>
              <Button size="sm" variant="ghost" onClick={() => onChangeKey(p)} data-testid={`provider-key-${p.id}`}>
                {p.keySet ? 'Change key' : 'Add key'}
              </Button>
            </>
          }
        >
          <div className="mt-1.5 flex flex-col gap-1 text-xs text-muted-foreground" data-testid={`provider-${p.id}`}>
            {p.keySecret && (
              <span className="flex flex-wrap items-center gap-1.5">
                <KeyRound className="size-3.5" /> <span className="whitespace-nowrap">Key in</span> <span className="font-mono text-foreground">{p.keySecret}</span>
                {!p.keySet && <Badge variant="destructive">Missing</Badge>}
              </span>
            )}
            <Health provider={p} />
            <span>{p.aliases.length ? <>Used by {p.aliases.map((a, i) => <span key={a}>{i ? ', ' : ''}<span className="font-mono text-foreground">{a}</span></span>)}</> : 'No alias routes here yet'}</span>
          </div>
        </Row>
      ))}
    </Rows>
  );
}
