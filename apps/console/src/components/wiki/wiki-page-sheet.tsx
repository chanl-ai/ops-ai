import { ShieldCheck } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { FieldRow, FieldSectionLabel } from '@/components/shared/field-row';
import { LoadingButton } from '@/components/shared/loading-button';
import { dateTime, plural, relativeTime } from '@/lib/format';
import type { WikiPageDetail } from '@/lib/types/wiki';

import { PROVENANCE, ProvenanceChip, VerifiedText } from './wiki-meta';

/** One page: what it says, where it came from, its versions, and the verify action. */
export function WikiPageSheet({
  page,
  open,
  onOpenChange,
  navigation,
  loading,
  verifying,
  onVerify,
}: {
  page?: WikiPageDetail;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  navigation?: DetailSheetNavigation;
  loading: boolean;
  verifying: boolean;
  onVerify: () => void;
}) {
  const p = page;
  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      testId="wiki-page-sheet"
      scrollKey={p?.id}
      navigation={navigation}
      title={p?.title ?? (loading ? 'Loading…' : '')}
      description={p ? `${p.collection} · v${p.version} · edited ${relativeTime(p.updatedAt)} by ${p.updatedBy}` : undefined}
      tags={p && <ProvenanceChip provenance={p.provenance} />}
      footerActions={
        p && (
          <LoadingButton size="sm" isLoading={verifying} onClick={onVerify} data-testid="wiki-verify">
            <ShieldCheck className="size-4" /> {p.verifiedAt ? 'Verify again' : 'Promote to verified'}
          </LoadingButton>
        )
      }
    >
      {p && (
        <div className="flex flex-col gap-6">
          {p.driftNote && (
            <p className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-warning-text" data-testid="wiki-drift">
              The source changed since v{p.version}: {p.driftNote}
            </p>
          )}
          <section className="flex flex-col gap-2">
            <FieldSectionLabel>Content</FieldSectionLabel>
            <p className="rounded-lg border bg-muted/30 p-3 text-sm leading-relaxed">{p.excerpt}</p>
          </section>
          <section className="flex flex-col gap-1">
            <FieldSectionLabel>Provenance</FieldSectionLabel>
            <FieldRow label="Came from" value={`${PROVENANCE[p.provenance].hint}: ${p.origin}`} />
            <FieldRow label="Owner" value={p.owner} />
            <FieldRow label="Verified" value={p.verifiedAt ? `${dateTime(p.verifiedAt)} by ${p.verifiedBy}` : <VerifiedText at={null} />} />
            <FieldRow label="Cited by" value={`${plural(p.citedBy, 'answer')} in 30 days`} />
          </section>
          <section className="flex flex-col gap-2">
            <FieldSectionLabel>Versions · {p.versions.length}</FieldSectionLabel>
            <ol className="flex flex-col gap-1.5 text-sm">
              {p.versions.map((v) => (
                <li key={v.version} className="flex items-baseline gap-2">
                  <span className="font-mono text-xs font-medium">v{v.version}</span>
                  <span>{v.note}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {v.by} · {relativeTime(v.at)}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </DetailSheet>
  );
}
