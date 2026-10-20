'use client';

import { GitPullRequestArrow } from 'lucide-react';

import { KnowledgeChangesQueue } from '@/components/knowledge/knowledge-changes-queue';
import { PageLayout } from '@/components/page-layout';

/** Proposed document changes across every knowledge base. */
export default function KnowledgeChangesPage() {
  return (
    <PageLayout switcher icon={GitPullRequestArrow} title="Knowledge changes" description="Proposed edits to knowledge documents">
      <KnowledgeChangesQueue />
    </PageLayout>
  );
}
