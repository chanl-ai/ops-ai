import { redirect } from 'next/navigation';

/** Sources merged into Connections: each connection's Knowledge tab holds what it syncs. */
export default function SourcesRedirect() {
  redirect('/integrations');
}
