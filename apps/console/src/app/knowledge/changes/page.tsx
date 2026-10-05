'use client';

import { GitPullRequestArrow } from 'lucide-react';

import { KnowledgeChangesQueue } from '@/components/knowledge/knowledge-changes-queue';
import { PageLayout } from '@/components/page-layout';

/** Proposed document changes across every knowledge base, decided by each document's owner. */
export default function KnowledgeChangesPage() {
  return (
    <PageLayout icon={GitPullRequestArrow} title="Knowledge changes" description="Document edits waiting for their owner">
      <KnowledgeChangesQueue />
    </PageLayout>
  );
}
