'use client';

import { use } from 'react';
import { notFound } from 'next/navigation';

import { McpLinkPage } from '@/components/channels/mcp/link-page';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { useFlagState } from '@/hooks/flag-queries';

/** One MCP link; like the MCP tab, only while the install turns mcp_gateway on. */
export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const flag = useFlagState('mcp_gateway');
  if (flag === 'loading') return <RecordSkeleton />;
  if (flag === 'off') notFound();
  return <McpLinkPage id={decodeURIComponent(id)} />;
}
