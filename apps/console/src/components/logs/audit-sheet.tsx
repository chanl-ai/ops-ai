'use client';

import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { KeyValues, Section } from '@/components/shared/surface';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateTime } from '@/lib/format';
import type { AuditEntry } from '@/lib/types/governance';

import { ActionBadge, ActorCell, TARGET_LABEL } from './log-meta';

/** One audit entry: who, what, the before and after of each changed field, and why. */
export function AuditSheet({ entry, navigation, onOpenChange }: { entry: AuditEntry | null; navigation?: DetailSheetNavigation; onOpenChange: (open: boolean) => void }) {
  const e = entry;
  return (
    <DetailSheet
      open={!!e}
      onOpenChange={onOpenChange}
      navigation={navigation}
      scrollKey={e?.id}
      testId="audit-sheet"
      title={e?.summary ?? 'Audit entry'}
      description={e ? `${dateTime(e.at)} · ${e.team}` : undefined}
      tags={e && <ActionBadge action={e.action} />}
    >
      {e && (
        <div className="flex flex-col gap-4">
          <Section title="Entry" flush bodyClassName="px-4">
            <KeyValues
              rows={[
                ['Actor', <ActorCell key="a" {...e.actor} />],
                ['Target', e.target.href ? <Link key="t" href={e.target.href} className="underline-offset-4 hover:underline">{TARGET_LABEL[e.target.type]} · {e.target.name}</Link> : `${TARGET_LABEL[e.target.type]} · ${e.target.name}`],
                ['Team', e.team],
                ['Request id', <code key="r" className="font-mono text-xs">{e.requestId}</code>],
              ]}
            />
          </Section>

          <Section title="Changes" flush>
            {e.diff.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-40">Field</TableHead>
                    <TableHead>Before</TableHead>
                    <TableHead className="w-6" />
                    <TableHead>After</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {e.diff.map((d) => (
                    <TableRow key={d.field}>
                      <TableCell className="align-top text-xs text-muted-foreground">{d.field}</TableCell>
                      <TableCell className="align-top whitespace-normal">
                        {d.before != null ? <span className="rounded-sm bg-red-50 px-1 text-red-800 line-through decoration-red-400/60 dark:bg-red-950/40 dark:text-red-300">{d.before}</span> : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="align-top">
                        <ArrowRight className="size-3.5 text-muted-foreground" />
                      </TableCell>
                      <TableCell className="align-top whitespace-normal">
                        {d.after != null ? <span className="rounded-sm bg-emerald-50 px-1 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">{d.after}</span> : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="px-4 py-3 text-sm text-muted-foreground">No field changes recorded for this action.</p>
            )}
          </Section>

          <Section title="Reason">
            <p className="text-sm">{e.reason ?? <span className="text-muted-foreground">No reason given.</span>}</p>
          </Section>
        </div>
      )}
    </DetailSheet>
  );
}
