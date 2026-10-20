import { redirect } from 'next/navigation';

/** Connect moved into Deployments as the MCP channel; old links land on that tab. */
export default function ConnectRedirect() {
  redirect('/channels/mcp');
}
