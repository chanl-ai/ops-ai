'use client';

import { notFound } from 'next/navigation';

import { McpLinksPage } from '@/components/channels/mcp/links-page';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { useFlagState } from '@/hooks/flag-queries';

/** Channels › MCP, the team's MCP links; it exists only while the install turns mcp_gateway on, else not found. */
export default function Page() {
  const flag = useFlagState('mcp_gateway');
  if (flag === 'loading') return <PageSkeleton statCards={1} tableRows={4} />;
  if (flag === 'off') notFound();
  return <McpLinksPage />;
}
