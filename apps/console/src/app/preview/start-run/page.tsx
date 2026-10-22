'use client';

import * as React from 'react';
import type { Row } from '@tanstack/react-table';
import { ArrowRight, Play, PlayCircle, Scale, Trash2 } from 'lucide-react';
import { useSearchParams } from 'next/navigation';

import { DataTableRowActions } from '@/components/data-table-row-actions';
import { PageLayout } from '@/components/page-layout';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StartDefinitionRunDialog, StartWorkflowRunDialog } from '@/components/workflows/start-run-dialog';

import { emailStart, formStart, NOTICE, sampleFiles, sampleFileWorkflows } from './_sample/data';

type Screen = 'composer' | 'form' | 'files-menu' | 'file-start';

const SCREENS: { id: Screen; title: string; description: string }[] = [
  { id: 'composer', title: 'Send a test email', description: 'Start run on a workflow an email starts: the trigger declares this form, and the email runs as if the mailbox delivered it.' },
  { id: 'form', title: 'A form with a file field', description: 'Start run on a workflow a form starts: a file field uploads or picks from Files, never a box for a file id.' },
  { id: 'files-menu', title: 'Files row menu', description: 'Each file offers to start a workflow with it.' },
  { id: 'file-start', title: 'Start a workflow with this file', description: 'Only workflows that take a file and that a person starts; the file arrives attached.' },
];

const noop = async () => undefined;

/**
 * Design mock for starting any workflow from its trigger's start form (c-466). The dialogs are the shipped components
 * with sample data; `?screen=` opens one of them. Starting does nothing on this page.
 */
export default function StartRunPreview() {
  const params = useSearchParams();
  const [open, setOpen] = React.useState<Screen | null>((params.get('screen') as Screen | null) ?? null);
  const row = { original: { id: NOTICE.fileId, name: NOTICE.name } } as unknown as Row<{ id: string; name: string }>;
  const shut = (o: boolean) => !o && setOpen(null);
  return (
    <PageLayout icon={PlayCircle} title="Start run" description="Design mock: one start dialog drawn from the trigger's start form, and starting from a file. Sample data; nothing runs.">
      <div className="grid gap-4 md:grid-cols-2">
        {SCREENS.map((s) => (
          <section key={s.id} data-screen={s.id}>
            <Card className="h-full">
              <CardHeader>
                <CardTitle>{s.title}</CardTitle>
                <CardDescription>{s.description}</CardDescription>
                <CardAction>
                  {s.id === 'files-menu' ? (
                    <div className="flex items-center gap-2 text-sm" data-testid="preview-files-row">
                      <span className="truncate">{NOTICE.name}</span>
                      <DataTableRowActions
                        row={row}
                        actions={[
                          { label: 'Open', icon: ArrowRight, onClick: () => undefined },
                          { label: 'Start a workflow with this file', icon: Play, onClick: () => setOpen('file-start') },
                          { label: 'Place legal hold', icon: Scale, onClick: () => undefined },
                          { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: () => undefined },
                        ]}
                      />
                    </div>
                  ) : (
                    <Button variant="outline" size="sm" onClick={() => setOpen(s.id)} data-testid={`preview-open-${s.id}`}>
                      Open
                    </Button>
                  )}
                </CardAction>
              </CardHeader>
            </Card>
          </section>
        ))}
      </div>
      <StartDefinitionRunDialog open={open === 'composer'} onOpenChange={shut} workflowName="Court order notices by email" latestVersion={2} liveVersion={null} paused={false} startForm={emailStart} onStart={noop} onStartForm={noop} file={NOTICE} fileSource={sampleFiles} />
      <StartDefinitionRunDialog open={open === 'form'} onOpenChange={shut} workflowName="Card dispute with evidence" latestVersion={3} liveVersion={3} paused={false} startForm={formStart} onStart={noop} onStartForm={noop} fileSource={sampleFiles} />
      <StartWorkflowRunDialog open={open === 'file-start'} onOpenChange={shut} file={NOTICE} source={sampleFileWorkflows} fileSource={sampleFiles} />
    </PageLayout>
  );
}
