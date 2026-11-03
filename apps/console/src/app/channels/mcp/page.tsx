'use client';

import { notFound } from 'next/navigation';

import { ChannelKindPage } from '@/components/channels/hub/pages';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { useFlagState } from '@/hooks/flag-queries';

/** The MCP channel exists only while the install turns mcp_gateway on; otherwise the page is not found. */
export default function Page() {
  const flag = useFlagState('mcp_gateway');
  if (flag === 'loading') return <PageSkeleton statCards={1} tableRows={4} />;
  if (flag === 'off') notFound();
  return <ChannelKindPage type="mcp" />;
}
