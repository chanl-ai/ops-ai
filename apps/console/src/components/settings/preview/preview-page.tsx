'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { History, Settings } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { Note } from '@/components/shared/setting/note';
import { Button } from '@/components/ui/button';

/** Header and the design-mock note for every /preview/settings page. Page actions go in `actions`, never mid-page. */
/** `history`: the page's changes are audited, and this links to the one Audit log reader. */
export function PreviewPageLayout({ title, description, actions, history = true, children }: { title: string; description: string; actions?: ReactNode; history?: boolean; children: ReactNode }) {
  return (
    <PageLayout
      icon={Settings}
      title={title}
      description={description}
      actions={
        <>
          {actions}
          {history && (
            <Button asChild variant="outline">
              <Link href="/logs/audit">
                <History className="size-4" /> History
              </Link>
            </Button>
          )}
        </>
      }
    >
      <div className="mx-auto flex max-w-4xl flex-col gap-6 pb-16">
        <Note tone="sample" title="Design mock">
          Sample data. Each card has its own Save, and a save here shows a message and stores nothing.
        </Note>
        {children}
      </div>
    </PageLayout>
  );
}
