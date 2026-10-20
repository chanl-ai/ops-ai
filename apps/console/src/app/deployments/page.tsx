import { redirect } from 'next/navigation';

/**
 * Deployments fold into Channels (c-242): the old address lands on the hub, which says where they went. An address that
 * named an agent keeps it, so the notice can link to where that agent's versions are live.
 */
export default async function DeploymentsMoved({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const agent = (await searchParams).agent;
  const id = Array.isArray(agent) ? agent[0] : agent;
  redirect(`/channels?from=deployments${id ? `&agent=${encodeURIComponent(id)}` : ''}`);
}
