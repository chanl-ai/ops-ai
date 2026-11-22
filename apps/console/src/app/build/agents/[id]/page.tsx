import { redirect } from 'next/navigation';

const TABS = ['settings', 'evals', 'channels', 'versions', 'usage', 'limits'];

/** The bare address opens Settings; an older `?tab=` link opens its tab's own address. */
export default async function AgentIndex({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string }> }) {
  const { id } = await params;
  const { tab } = await searchParams;
  redirect(`/build/agents/${id}/${tab && TABS.includes(tab) ? tab : 'settings'}`);
}
