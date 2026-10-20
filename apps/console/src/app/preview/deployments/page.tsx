import { redirect } from 'next/navigation';

/** Deployments fold into Channels, so the old address lands on the Channels hub, which says where they went. */
export default function DeploymentsMoved() {
  redirect('/preview/channels?from=deployments');
}
