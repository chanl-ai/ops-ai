'use client';

import * as React from 'react';
import { Globe, KeyRound } from 'lucide-react';

import { EgressHostForm } from '@/components/settings/preview/egress-host-form';
import { SecretForm } from '@/components/settings/preview/secret-form';
import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { Note } from '@/components/shared/setting/note';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DIALOGS } from '@/lib/settings-preview';
import { usePreviewStore, useViewerRole } from '@/lib/settings-preview-store';
import Link from 'next/link';

const OPERATION_HOST = 'regional.statements.harborpine.example';
const NEEDED_SECRET = 'REGION_ROUTING_KEY';

/**
 * A tool page that meets two missing settings and opens their forms in place. The dialogs are the same components as
 * Govern › Security's Egress and Secrets sections; adding here shows there.
 */
export default function ToolPageExample() {
  const { can } = useViewerRole();
  const locked = !can('Security admin');
  const hosts = usePreviewStore((s) => s.hosts);
  const secrets = usePreviewStore((s) => s.secrets);
  const [hostOpen, setHostOpen] = React.useState(false);
  const [secretOpen, setSecretOpen] = React.useState(false);
  const hostAllowed = hosts.some((h) => h.host === OPERATION_HOST);
  const secretExists = secrets.some((s) => s.name === NEEDED_SECRET);
  return (
    <PreviewPageLayout title="Statement lookup" description="A tool module, shown only to place the settings dialogs" history={false}>
      {!hostAllowed ? (
        <Note tone="warning" title={`${OPERATION_HOST} is not an allowed host`}>
          <span className="flex flex-wrap items-center gap-3">
            Calls to it are refused before anything is sent.
            <Button size="sm" variant="outline" onClick={() => setHostOpen(true)} disabled={locked}>
              Add allowed host
            </Button>
            {locked && <span className="text-xs">Only a Security admin can add one.</span>}
          </span>
        </Note>
      ) : (
        <EntityRow name={OPERATION_HOST} icon={<Globe className="size-4" />} meta="Allowed. Calls to it go out." />
      )}
      {!secretExists ? (
        <Note tone="warning" title={`{{${NEEDED_SECRET}}} names a secret that does not exist`}>
          <span className="flex flex-wrap items-center gap-3">
            The header would be sent with the text unchanged.
            <Button size="sm" variant="outline" onClick={() => setSecretOpen(true)} disabled={locked}>
              Add secret
            </Button>
          </span>
        </Note>
      ) : (
        <EntityRow name={NEEDED_SECRET} icon={<KeyRound className="size-4" />} meta="Found. The header is filled in at call time." />
      )}
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Every dialog and its page</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Dialog</TableHead>
              <TableHead>Form</TableHead>
              <TableHead>Same form on</TableHead>
              <TableHead>Opened from</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {DIALOGS.map((d) => (
              <TableRow key={d.dialog}>
                <TableCell className="font-medium">{d.dialog}</TableCell>
                <TableCell>
                  <code className="font-mono text-xs">{d.form}</code>
                </TableCell>
                <TableCell>
                  <Link href={d.mother} className="text-primary underline-offset-4 hover:underline">
                    {d.motherLabel}
                  </Link>
                </TableCell>
                <TableCell className="whitespace-normal text-muted-foreground">{d.opensFrom}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <EgressHostForm shell="dialog" open={hostOpen} onOpenChange={setHostOpen} presetHost={OPERATION_HOST} />
      <SecretForm shell="dialog" open={secretOpen} onOpenChange={setSecretOpen} presetName={NEEDED_SECRET} />
    </PreviewPageLayout>
  );
}
